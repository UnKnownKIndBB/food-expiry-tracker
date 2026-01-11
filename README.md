# 🍲 AI Food Expiry & Waste Tracker

An intelligent local-first tool that helps reduce household food waste by automatically reading expiry dates from food packaging photos, maintaining smart inventory, sending timely alerts, and providing waste analytics & sustainability insights.

![Demo - Expiry Detection](app.jpeg)  
*(Add 2–3 nice screenshots here after running the app)*

## ✨ Key Features

- **Automatic expiry date extraction** using OCR on photos of food labels
- Manual entry with category, quantity & location support
- **Proactive alerts** (critical ≤1 day, warning ≤3 days, info ≤7 days)
- Waste analytics: monthly trends, category-wise waste rate, money & CO₂ impact
- Actionable insights & recommendations
- **Web interface** (Streamlit) – photo upload, dashboard, alerts preview

## 🛠️ Tech Stack 

- **Core Language**: Python 3.12+
- **OCR & Vision**: OpenCV + pytesseract + Tesseract OCR
- **Database**: SQLite (local & lightweight)
- **Analytics**: Pure Python heuristic engine
- **Web UI**: Streamlit (simple, beautiful, Python-only)
- **Logging**: Loguru
- **Future**: Planned multimodal LLM (Granite Vision / Llama 3.2 Vision) + RAG + Agentic AI

## 🚀 Quick Start

### Prerequisites
- Python 3.9–3.12
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) installed  
  → Windows: Install → Add to PATH or set path in `ocr_engine.py`

### Installation

```bash
# Clone / download the repo
git clone https://github.com/yourusername/food-expiry-tracker.git
cd food-expiry-tracker

# Install dependencies
pip install -r requirements.txt



## Responsible AI Considerations

- **Privacy**: All processing is local-first — no images or personal data are sent to any cloud.
- **Fairness & Bias**: Rule-based OCR + heuristic date parsing avoids model bias; works equally on all label formats.
- **Transparency**: Every expiry detection shows confidence score and raw text match.
- **Ethics**: No harmful use — goal is only to reduce food waste and promote sustainability.
- **Limitations**: OCR may struggle with very poor lighting/handwriting — manual entry fallback provided.
