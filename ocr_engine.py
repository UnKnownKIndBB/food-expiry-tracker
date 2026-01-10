# Core OCR Engine for Food Expiry Date Extraction

import cv2
import pytesseract
import numpy as np
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from loguru import logger

logger.add("logs/ocr_engine.log", rotation="10 MB")

UTC = timezone.utc


# ───────────────────────────────────────────────────────────────
#          VERY IMPORTANT - Windows Fix
# ───────────────────────────────────────────────────────────────
# Change this path to YOUR actual Tesseract installation location!
# Common paths:
#   C:\Program Files\Tesseract-OCR\tesseract.exe          ← most common
#   C:\Program Files (x86)\Tesseract-OCR\tesseract.exe    ← 32-bit version
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Set the path globally (must be before any pytesseract call)
if Path(TESSERACT_PATH).is_file():
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    logger.info(f"Tesseract path set: {TESSERACT_PATH}")
else:
    logger.error(f"Tesseract executable NOT found at: {TESSERACT_PATH}")
    logger.error("Please install Tesseract and update TESSERACT_PATH variable")
    # You can continue without crashing, but OCR will fail


class ImagePreprocessor:
    """Image preprocessing pipeline optimized for expiry date OCR"""

    @staticmethod
    def load_image(image_path: str) -> np.ndarray:
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {image_path}")

        img = cv2.imread(str(path))
        if img is None:
            raise ValueError(f"Failed to load image: {image_path}")
        logger.debug(f"Image loaded: {image_path} ({img.shape})")
        return img

    @staticmethod
    def convert_to_grayscale(image: np.ndarray) -> np.ndarray:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def resize_image(image: np.ndarray, target_width: int = 900) -> np.ndarray:
        h, w = image.shape[:2]
        if w <= target_width:
            return image
        ratio = target_width / w
        return cv2.resize(image, (target_width, int(h * ratio)), interpolation=cv2.INTER_LINEAR)

    @staticmethod
    def enhance_contrast(image: np.ndarray) -> np.ndarray:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(image)

    @staticmethod
    def preprocess(image: np.ndarray) -> np.ndarray:
        gray = ImagePreprocessor.convert_to_grayscale(image)
        resized = ImagePreprocessor.resize_image(gray)

        contrasted = ImagePreprocessor.enhance_contrast(resized)
        denoised = cv2.fastNlMeansDenoising(contrasted, h=10)
        blurred = cv2.GaussianBlur(denoised, (3, 3), 0)
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        morphed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)

        logger.debug("OCR preprocessing completed")
        return morphed


class DateExtractor:
    """Advanced date extraction from OCR text with many common expiry formats"""

    DATE_PATTERNS = [
        r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b',
        r'\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b',
        r'\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b',
        r'\b(\d{1,2})\s*(?:st|nd|rd|th)?\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(\d{4})\b',
        r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(\d{1,2})(?:st|nd|rd|th)?[,.\s]*(\d{4})\b',
        r'(?:EXP|Exp|Expiry|Best Before|Use By|BB|USE BY|Sell By|MFG|Manufactured)\s*[:=]?\s*(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})',
        r'(?:EXP|Exp|Expiry|Best Before|Use By)\s*[:=]?\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})',
    ]

    MONTH_MAP = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }

    @classmethod
    def parse_date(cls, text: str) -> Optional[datetime]:
        for pattern in cls.DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue

            groups = match.groups()
            if len(groups) != 3:
                continue

            if not groups[1].isdigit():
                month_str = groups[1].lower()[:3]
                month = cls.MONTH_MAP.get(month_str)
                if not month:
                    continue
                day, year = groups[0], groups[2]
            else:
                a, b, c = map(int, [g for g in groups if g.isdigit()])
                if 1 <= a <= 31 and 1 <= b <= 12:
                    day, month, year = a, b, c
                else:
                    day, month, year = b, a, c

            if year < 100:
                year += 2000 if year < 50 else 1900

            try:
                dt = datetime(year, month, day, tzinfo=UTC)
                if 2020 <= year <= 2035:
                    return dt
            except ValueError:
                continue

        return None

    @classmethod
    def extract_potential_dates(cls, text: str) -> List[Dict[str, any]]:
        candidates = []
        for pattern in cls.DATE_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                raw = match.group(0)
                dt = cls.parse_date(raw)
                if dt:
                    candidates.append({
                        'date': dt,
                        'raw': raw,
                        'confidence': 0.85
                    })
        return candidates

    @classmethod
    def select_best_expiry(cls, candidates: List[Dict]) -> Optional[Dict]:
        if not candidates:
            return None

        now = datetime.now(UTC)
        scored = []

        for cand in candidates:
            days = (cand['date'] - now).days
            conf = cand['confidence']

            if 1 <= days <= 540:
                conf *= 1.4
            elif 1 <= days <= 1825:
                conf *= 0.9
            else:
                conf *= 0.3

            scored.append({**cand, 'confidence': min(conf, 1.0), 'days_until': days})

        return max(scored, key=lambda x: x['confidence']) if scored else None


class FoodExpiryDetector:
    """Main OCR-based expiry date detector"""

    def __init__(self, tesseract_cmd: Optional[str] = None, lang: str = 'eng'):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

        self.lang = lang
        self.preprocessor = ImagePreprocessor()

        # Graceful version check (won't crash if path is wrong)
        try:
            version = pytesseract.get_tesseract_version()
            logger.info(f"FoodExpiryDetector initialized (Tesseract v{version})")
        except Exception as e:
            logger.warning(f"Could not get Tesseract version: {e}")
            logger.warning("Make sure Tesseract is installed and path is correct")

    def _extract_text(self, image: np.ndarray) -> Tuple[str, float]:
        texts, confs = [], []

        for psm in [6, 7, 11, 3]:
            try:
                config = f'--psm {psm} --oem 3 -l {self.lang}'
                text = pytesseract.image_to_string(image, config=config)

                data = pytesseract.image_to_data(image, config=config,
                                               output_type=pytesseract.Output.DICT)
                valid_confs = [int(c) for c in data['conf'] if int(c) >= 0]
                avg = np.mean(valid_confs) / 100.0 if valid_confs else 0.0

                if text.strip():
                    texts.append(text)
                    confs.append(avg)
            except Exception:
                continue

        if not texts:
            return "", 0.0

        return " ".join(texts), float(np.mean(confs))

    def extract_expiry_date(self, image_path: str) -> Dict[str, any]:
        try:
            raw_img = self.preprocessor.load_image(image_path)
            processed = self.preprocessor.preprocess(raw_img)

            text, ocr_conf = self._extract_text(processed)
            logger.debug(f"OCR confidence: {ocr_conf:.2%} | Text length: {len(text)}")

            candidates = DateExtractor.extract_potential_dates(text)

            if not candidates:
                return {
                    'success': False,
                    'error': 'No date pattern matched in text',
                    'raw_text': text[:200] + "..." if len(text) > 200 else text,
                    'ocr_confidence': ocr_conf
                }

            best = DateExtractor.select_best_expiry(candidates)

            if not best:
                return {
                    'success': False,
                    'error': 'Found dates but none valid as future expiry',
                    'candidates': [c['raw'] for c in candidates],
                    'ocr_confidence': ocr_conf
                }

            days_left = (best['date'] - datetime.now(UTC)).days

            return {
                'success': True,
                'date': best['date'].strftime('%Y-%m-%d'),
                'raw_text': best['raw'],
                'confidence': round(best['confidence'], 3),
                'days_until_expiry': days_left,
                'ocr_confidence': round(ocr_conf, 3),
                'note': 'Extracted successfully'
            }

        except Exception as e:
            logger.exception(f"Critical error during expiry detection: {image_path}")
            return {
                'success': False,
                'error': str(e),
                'ocr_confidence': 0.0
            }


# ───────────────────────────────────────────────────────────────
#                     Quick Test / Demo
# ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # IMPORTANT: Use your real path here!
    detector = FoodExpiryDetector(
        tesseract_cmd=r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        # If installed in Program Files (x86):
        # tesseract_cmd=r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
    )

    test_images = [
        "sample_labels/milk.jpeg",
        # "sample_labels/yogurt.jpg",
        # Add your real image paths here
    ]

    for img_path in test_images:
        print(f"\n{'='*60}\nProcessing: {img_path}\n{'='*60}")
        result = detector.extract_expiry_date(img_path)

        if result['success']:
            print(f"✓ Success!")
            print(f"  Date:           {result['date']}")
            print(f"  Days remaining: {result['days_until_expiry']}")
            print(f"  Confidence:     {result['confidence']:.1%} (OCR: {result['ocr_confidence']:.1%})")
            print(f"  Raw match:      {result.get('raw_text')}")
        else:
            print(f"✗ Failed: {result['error']}")
            if 'candidates' in result:
                print("  Candidates:", result['candidates'])
            print(f"  OCR confidence: {result['ocr_confidence']:.1%}")