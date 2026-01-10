# main.py
# Main application entry point for AI Food Expiry Tracker
# Updated: January 2026

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from database import FoodDatabase, FoodItem
from ocr_engine import FoodExpiryDetector
from alerts import AlertSystem
from analytics import FoodAnalytics
from loguru import logger

# Setup logging
logger.add("logs/app.log", rotation="500 MB", level="INFO")

UTC = timezone.utc


def now_utc() -> datetime:
    """Helper: current time in UTC"""
    return datetime.now(UTC)


class FoodExpiryTrackerApp:
    """Main application class"""

    def __init__(self):
        """Initialize application components"""
        self.db = FoodDatabase()
        self.detector = FoodExpiryDetector()
        self.alerts = AlertSystem(self.db)
        self.analytics = FoodAnalytics(self.db)
        logger.info("Application initialized")

    def add_food_from_image(
        self,
        image_path: str,
        name: Optional[str] = None,
        category: str = "other",
        quantity: float = 1.0,
        unit: str = "units",
        location: str = "Refrigerator"
    ) -> dict:
        """Add food item using OCR from image"""
        logger.info(f"Processing food image: {image_path}")

        if not Path(image_path).is_file():
            return {'success': False, 'message': f"Image not found: {image_path}"}

        try:
            ocr_result = self.detector.extract_expiry_date(image_path)

            if not ocr_result.get('success', False):
                return {
                    'success': False,
                    'message': f"OCR failed: {ocr_result.get('error', 'Unknown error')}",
                    'error': ocr_result.get('error')
                }

            expiry_str = ocr_result['date']
            expiry_date = datetime.fromisoformat(expiry_str)

            food = FoodItem(
                name=(name or "Unknown Food").strip(),
                category=category.strip(),
                purchase_date=now_utc(),
                expiry_date=expiry_date,
                quantity=quantity,
                unit=unit.strip(),
                location=location.strip(),
                status='active',
                ocr_confidence=ocr_result.get('confidence', 0.0),
                image_path=image_path,
                notes=f"Extracted from image - {ocr_result.get('raw_text', '')}"
            )

            item_id = self.db.add_food_item(food)

            days_until = ocr_result.get('days_until_expiry', -1)
            if days_until >= 0:
                for threshold_name, threshold_days in self.alerts.ALERT_THRESHOLDS.items():
                    if days_until <= threshold_days:
                        self.alerts.log_alert(item_id, threshold_name, days_until)

            return {
                'success': True,
                'item_id': item_id,
                'message': f"✓ {food.name} added successfully",
                'expiry_date': expiry_str,
                'days_remaining': days_until,
                'confidence': ocr_result.get('confidence', 0.0)
            }

        except ValueError as e:
            logger.error(f"Invalid date format from OCR: {e}")
            return {'success': False, 'message': f"Invalid expiry date format: {e}"}
        except Exception as e:
            logger.exception("Failed to add food from image")
            return {'success': False, 'message': f"Error: {str(e)}"}

    def add_food_manual(
        self,
        name: str,
        category: str,
        expiry_date_str: str,
        quantity: float = 1.0,
        unit: str = "units",
        location: str = "Refrigerator"
    ) -> dict:
        """Manually add food item"""
        try:
            name_clean = name.strip()
            if not name_clean:
                raise ValueError("Food name cannot be empty")

            expiry = datetime.fromisoformat(expiry_date_str.strip())
            if expiry < now_utc():
                logger.warning(f"Added expired item: {name_clean} ({expiry_date_str})")

            food = FoodItem(
                name=name_clean,
                category=category.strip(),
                purchase_date=now_utc(),
                expiry_date=expiry,
                quantity=quantity,
                unit=unit.strip(),
                location=location.strip(),
                status='active',
                notes="Manually entered"
            )

            item_id = self.db.add_food_item(food)
            days_until = (expiry - now_utc()).days

            for threshold_name, threshold_days in self.alerts.ALERT_THRESHOLDS.items():
                if days_until <= threshold_days:
                    self.alerts.log_alert(item_id, threshold_name, days_until)

            return {
                'success': True,
                'item_id': item_id,
                'message': f"✓ {name_clean} added successfully",
                'days_remaining': days_until
            }

        except ValueError as ve:
            logger.error(f"Validation error: {ve}")
            return {'success': False, 'message': f"Invalid input: {str(ve)}"}
        except Exception as e:
            logger.exception("Failed to add food manually")
            return {'success': False, 'message': f"Error: {str(e)}"}

    def check_expiring_items(self, days: int = 7) -> dict:
        """Check for items expiring within given days"""
        if days < 1:
            days = 7

        expiring = self.alerts.get_expiring_items(days=days)
        critical = self.alerts.get_critical_alerts()
        summary = self.alerts.generate_alert_summary()

        return {
            'total_expiring': len(expiring),
            'critical_count': len(critical),
            'summary': summary,
            'items': expiring
        }

    def view_inventory(self, status: str = "active") -> dict:
        """View current inventory"""
        items = self.db.get_all_items(status=status)

        formatted = []
        now = now_utc()
        for item in items:
            days_left = (item.expiry_date - now).days if item.expiry_date else -999
            formatted.append({
                'id': item.id,
                'name': item.name,
                'category': item.category,
                'quantity': f"{item.quantity:g} {item.unit}",
                'expiry': item.expiry_date.strftime('%Y-%m-%d') if item.expiry_date else "N/A",
                'days_left': days_left,
                'location': item.location,
                'status': item.status
            })

        return {'count': len(formatted), 'items': formatted}

    # ... (other methods remain mostly unchanged, just minor cleanups)

    def close(self):
        """Cleanup"""
        self.db.close()
        logger.info("Application closed")


def main():
    parser = argparse.ArgumentParser(
        description='AI-Based Food Expiry & Waste Tracker',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py add-image data/labels/milk.jpg --name "Amul Milk" --category dairy
  python main.py add-manual --name "Banana" --category fruits --expiry 2026-02-05
  python main.py inventory
  python main.py dashboard
  python main.py report
        """
    )

    subparsers = parser.add_subparsers(dest='command', required=True)

    # Add image
    p_img = subparsers.add_parser('add-image', help='Add food from photo')
    p_img.add_argument('image_path', type=str)
    p_img.add_argument('--name', type=str)
    p_img.add_argument('--category', default='other')
    p_img.add_argument('--quantity', type=float, default=1.0)
    p_img.add_argument('--unit', default='units')
    p_img.add_argument('--location', default='Refrigerator')

    # Add manual
    p_manual = subparsers.add_parser('add-manual', help='Add food manually')
    p_manual.add_argument('--name', required=True)
    p_manual.add_argument('--category', required=True)
    p_manual.add_argument('--expiry', required=True, help='YYYY-MM-DD')
    p_manual.add_argument('--quantity', type=float, default=1.0)
    p_manual.add_argument('--unit', default='units')
    p_manual.add_argument('--location', default='Refrigerator')

    # Other commands...
    subparsers.add_parser('inventory')
    subparsers.add_parser('dashboard')
    subparsers.add_parser('report')

    p_alert = subparsers.add_parser('send-alerts')
    p_alert.add_argument('email', help='recipient email')

    p_exp = subparsers.add_parser('check-expiring')
    p_exp.add_argument('--days', type=int, default=7)

    args = parser.parse_args()

    app = FoodExpiryTrackerApp()

    try:
        if args.command == 'add-image':
            result = app.add_food_from_image(
                args.image_path, args.name, args.category,
                args.quantity, args.unit, args.location
            )
            print(f"{'✓' if result['success'] else '✗'} {result['message']}")
            if result['success']:
                print(f"  Item ID     : {result['item_id']}")
                print(f"  Expiry      : {result['expiry_date']}")
                print(f"  Days left   : {result['days_remaining']}")
                print(f"  Confidence  : {result['confidence']:.1%}")

        elif args.command == 'add-manual':
            result = app.add_food_manual(
                args.name, args.category, args.expiry,
                args.quantity, args.unit, args.location
            )
            print(f"{'✓' if result['success'] else '✗'} {result['message']}")
            if result['success']:
                print(f"  Days remaining: {result['days_remaining']}")

        elif args.command == 'check-expiring':
            result = app.check_expiring_items(args.days)
            print(result['summary'])

        elif args.command == 'inventory':
            result = app.view_inventory()
            if not result['count']:
                print("\n📦 Your inventory is empty.\n")
                return

            print(f"\n📦 INVENTORY ({result['count']} items)\n")
            print(f"{'ID':<5} {'Name':<22} {'Cat':<10} {'Expiry':<12} {'Days':<6} {'Loc':<15}")
            print("-" * 85)
            for i in result['items']:
                print(f"{i['id']:<5} {i['name'][:21]:<22} {i['category'][:9]:<10} "
                      f"{i['expiry']:<12} {i['days_left']:<6} {i['location'][:14]:<15}")

        elif args.command == 'dashboard':
            result = app.get_dashboard()
            s = result['stats']
            print("\n┌──────────────────────────────────────────────┐")
            print("│             FOOD DASHBOARD (30 days)         │")
            print("└──────────────────────────────────────────────┘")
            print(f"  Consumed : {s['items_consumed']}")
            print(f"  Shared   : {s['items_shared']}")
            print(f"  Wasted   : {s['items_wasted']}")
            print(f"  Waste %  : {s['waste_rate_percent']}%")
            print(f"  Cost lost: ₹{s['estimated_savings_wasted']:.0f}")
            print("\nInsights:")
            for ins in result['insights']:
                print(f"  • {ins}")

        elif args.command == 'report':
            print(app.export_report())

        elif args.command == 'send-alerts':
            result = app.send_alerts(args.email)
            print(f"{'✓' if result['sent'] else '✗'} {result['message']}")

    except KeyboardInterrupt:
        print("\nCancelled by user.")
    except Exception as e:
        logger.exception("Critical error in main")
        print(f"\n✗ Unexpected error: {str(e)}")
    finally:
        app.close()


if __name__ == "__main__":
    main()


