# Modern alert & notification system for expiring food items

import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Any
from loguru import logger
from dotenv import load_dotenv

# Optional modern email service (recommended)
try:
    import resend
    HAS_RESEND = True
except ImportError:
    HAS_RESEND = False
    logger.warning("resend package not installed → falling back to SMTP (less secure)")

load_dotenv()
logger.add("logs/alerts.log", rotation="10 MB")

UTC = timezone.utc


class AlertError(Exception):
    """Base exception for alert system errors"""
    pass


class AlertSystem:
    """Notification system for food expiry alerts"""

    ALERT_THRESHOLDS = {
        'critical': 1,   # 1 day or less
        'warning': 3,    # 3 days or less
        'info': 7        # 7 days or less
    }

    def __init__(self, database, email_config: Optional[Dict] = None):
        self.db = database
        self.email_config = email_config or self._load_email_config()
        self.notifications_sent = 0
        self._validate_and_prepare_email()
        logger.info("AlertSystem initialized")

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def _load_email_config(self) -> Dict[str, Any]:
        """Load config from environment variables"""
        config = {
            'provider': os.getenv('EMAIL_PROVIDER', 'smtp').lower(),
            'sender_email': os.getenv('EMAIL_SENDER'),
            'sender_name': os.getenv('EMAIL_SENDER_NAME', 'Food Expiry Tracker'),
            'resend_api_key': os.getenv('RESEND_API_KEY'),
            'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
            'smtp_port': int(os.getenv('SMTP_PORT', '587')),
            'smtp_password': os.getenv('EMAIL_PASSWORD'),
        }
        return config

    def _validate_and_prepare_email(self) -> None:
        """Validate config and decide sending method"""
        cfg = self.email_config

        if cfg.get('provider') == 'resend' and HAS_RESEND and cfg.get('resend_api_key'):
            resend.api_key = cfg['resend_api_key']
            logger.info("Email provider: Resend (recommended modern API)")
            cfg['sending_method'] = 'resend'
            return

        # Fallback to SMTP
        required_smtp = ['sender_email', 'smtp_password', 'smtp_server', 'smtp_port']
        missing = [k for k in required_smtp if not cfg.get(k)]

        if missing:
            logger.warning(
                f"Email alerts DISABLED - missing SMTP keys: {', '.join(missing)}\n"
                "Set EMAIL_SENDER, EMAIL_PASSWORD, SMTP_SERVER in .env"
            )
            cfg['sending_method'] = None
        else:
            logger.info("Email provider: SMTP (legacy mode)")
            cfg['sending_method'] = 'smtp'

    def check_expiry_status(self, expiry_date: datetime) -> Dict[str, Any]:
        """Determine expiry status and alert level"""
        now = self._now()
        days_remaining = (expiry_date - now).days

        if days_remaining < 0:
            return {
                'status': 'expired',
                'days_remaining': days_remaining,
                'alert_level': 'critical',
                'message': '⚠️ Item has EXPIRED'
            }
        elif days_remaining <= self.ALERT_THRESHOLDS['critical']:
            return {
                'status': 'expiring',
                'days_remaining': days_remaining,
                'alert_level': 'critical',
                'emoji': '🔴',
                'message': f'URGENT - Expires in {days_remaining} day(s)'
            }
        elif days_remaining <= self.ALERT_THRESHOLDS['warning']:
            return {
                'status': 'expiring',
                'days_remaining': days_remaining,
                'alert_level': 'warning',
                'emoji': '🟠',
                'message': f'Warning - Expires in {days_remaining} days'
            }
        elif days_remaining <= self.ALERT_THRESHOLDS['info']:
            return {
                'status': 'expiring',
                'days_remaining': days_remaining,
                'alert_level': 'info',
                'emoji': 'ℹ️',
                'message': f'Info - Expires in {days_remaining} days'
            }
        else:
            return {
                'status': 'safe',
                'days_remaining': days_remaining,
                'alert_level': 'none',
                'emoji': '✓',
                'message': f'Safe - {days_remaining} days remaining'
            }

    def get_expiring_items(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get items expiring within N days with status info"""
        items = self.db.get_expiring_items(days=days)
        return [
            {
                'item': item,
                'status_info': self.check_expiry_status(item.expiry_date),
                'full_message': f"{item.name} - {self.check_expiry_status(item.expiry_date)['message']}"
            }
            for item in items
        ]

    def generate_alert_summary(self) -> str:
        """Generate readable text summary of current alerts"""
        expiring = self.get_expiring_items(days=7)

        if not expiring:
            return "✓ No items expiring in the next 7 days. Your fridge looks good!"

        lines = [
            f"🍲 FOOD EXPIRY ALERT - {self._now().strftime('%Y-%m-%d %H:%M')} UTC",
            "=" * 60,
            ""
        ]

        groups = {'critical': [], 'warning': [], 'info': []}

        for entry in expiring:
            level = entry['status_info']['alert_level']
            if level in groups:
                groups[level].append(entry)

        for level, items in [('critical', groups['critical']),
                            ('warning', groups['warning']),
                            ('info', groups['info'])]:
            if items:
                emoji = {'critical': '🔴', 'warning': '🟠', 'info': 'ℹ️'}[level]
                title = {
                    'critical': 'CRITICAL (Today or tomorrow)',
                    'warning': 'WARNING (within 3 days)',
                    'info': 'INFO (within 7 days)'
                }[level]
                lines.append(f"{emoji} {title}:")
                for entry in items:
                    days = entry['status_info']['days_remaining']
                    lines.append(f"  • {entry['item'].name} ({days} day{'s' if days != 1 else ''})")
                lines.append("")

        lines.extend([
            "=" * 60,
            "💡 Tip: Use, freeze or share items that are expiring soon!",
            "Track more → reduce waste → better planet 🌱"
        ])

        return "\n".join(lines)

    def send_single_email_alert(self, recipient: str, item_name: str, days_remaining: int,
                               alert_level: str = 'warning') -> bool:
        """Send email about single expiring item"""
        if not self.email_config or not self.email_config.get('sending_method'):
            logger.warning("Email sending disabled - no valid config")
            return False

        status = self.check_expiry_status(datetime.now(UTC) + timedelta(days=days_remaining))
        emoji = status.get('emoji', 'ℹ️')
        urgency = status['message']

        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <h2>{emoji} Food Expiry Alert</h2>
                <p><strong>{urgency}</strong></p>
                <p>Your item <strong>"{item_name}"</strong> is expiring in 
                   <strong>{days_remaining} day{'s' if days_remaining != 1 else ''}</strong>.</p>
                <p>Quick actions:</p>
                <ul>
                    <li>Use it today or tomorrow</li>
                    <li>Freeze for later</li>
                    <li>Share with neighbors/community</li>
                </ul>
                <hr style="border: 0; border-top: 1px solid #eee;">
                <p style="font-size: 0.9em; color: #666;">
                    Sent by AI Food Expiry Tracker • Fighting food waste • SDG 12
                </p>
            </body>
        </html>
        """

        try:
            if self.email_config['sending_method'] == 'resend':
                resend.Emails.send({
                    "from": f"{self.email_config['sender_name']} <{self.email_config['sender_email']}>",
                    "to": recipient,
                    "subject": f"🍲 Expiry Alert: {item_name}",
                    "html": html_content
                })
            else:
                # Legacy SMTP (keep for compatibility, but not recommended)
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart
                import smtplib

                msg = MIMEMultipart('alternative')
                msg['Subject'] = f"🍲 Expiry Alert: {item_name}"
                msg['From'] = self.email_config['sender_email']
                msg['To'] = recipient
                msg.attach(MIMEText(html_content, 'html'))

                with smtplib.SMTP(self.email_config['smtp_server'],
                                self.email_config['smtp_port']) as server:
                    server.starttls()
                    server.login(self.email_config['sender_email'],
                               self.email_config['smtp_password'])
                    server.send_message(msg)

            logger.info(f"Alert sent to {recipient} about '{item_name}'")
            self.notifications_sent += 1
            return True

        except Exception as e:
            logger.error(f"Failed to send alert to {recipient}: {e}")
            return False

    def send_batch_alerts(self, recipient: str) -> Dict[str, Any]:
        """Send summary email with all current alerts"""
        if not self.email_config or not self.email_config.get('sending_method'):
            return {'sent': False, 'count': 0, 'message': 'Email sending disabled - no valid config'}

        summary_text = self.generate_alert_summary()

        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; background:#f8f9fa; padding:20px;">
                <div style="max-width:600px; margin:auto; background:white; padding:25px; border-radius:8px;">
                    <h2>🍲 Daily Food Expiry Summary</h2>
                    <pre style="background:#f0f0f0; padding:15px; border-radius:6px; white-space:pre-wrap; font-family:monospace;">
{summary_text}
                    </pre>
                    <p style="font-size:0.9em; color:#555; margin-top:20px;">
                        Keep tracking → reduce waste → better world 🌍<br>
                        <small>AI Food Expiry Tracker • {self._now().strftime('%Y-%m-%d')}</small>
                    </p>
                </div>
            </body>
        </html>
        """

        try:
            if self.email_config['sending_method'] == 'resend':
                resend.Emails.send({
                    "from": f"{self.email_config['sender_name']} <{self.email_config['sender_email']}>",
                    "to": recipient,
                    "subject": "🍲 Daily Food Expiry Summary",
                    "html": html
                })
            else:
                # SMTP fallback
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart
                import smtplib

                msg = MIMEMultipart('alternative')
                msg['Subject'] = "🍲 Daily Food Expiry Summary"
                msg['From'] = self.email_config['sender_email']
                msg['To'] = recipient
                msg.attach(MIMEText(html, 'html'))

                with smtplib.SMTP(self.email_config['smtp_server'],
                                self.email_config['smtp_port']) as server:
                    server.starttls()
                    server.login(self.email_config['sender_email'],
                               self.email_config['smtp_password'])
                    server.send_message(msg)

            count = len(self.get_expiring_items(days=7))
            logger.info(f"Batch alert sent to {recipient} ({count} items)")
            self.notifications_sent += 1

            return {
                'sent': True,
                'count': count,
                'message': f"Summary sent ({count} items tracked)"
            }

        except Exception as e:
            logger.error(f"Batch alert failed: {e}")
            return {'sent': False, 'count': 0, 'message': str(e)}

    def log_alert(self, food_item_id: int, alert_type: str, days_remaining: int) -> bool:
        """Record alert in database"""
        try:
            return self.db.add_alert(food_item_id, alert_type, days_remaining)
        except Exception as e:
            logger.error(f"Failed to log alert for item {food_item_id}: {e}")
            return False

    def get_statistics(self) -> Dict[str, Any]:
        """Current alert system statistics"""
        active_items = self.db.get_all_items('active')
        expiring = self.get_expiring_items(7)
        critical = [e for e in expiring if e['status_info']['alert_level'] == 'critical']

        avg_days = 0
        valid_expiry_count = 0
        for item in active_items:
            if item.expiry_date:
                days = (item.expiry_date - self._now()).days
                avg_days += days
                valid_expiry_count += 1

        avg_days = avg_days / valid_expiry_count if valid_expiry_count > 0 else 0

        return {
            'total_tracked_items': len(active_items),
            'expiring_this_week': len(expiring),
            'critical_items': len(critical),
            'notifications_sent_total': self.notifications_sent,
            'average_days_remaining': round(avg_days, 1)
        }


if __name__ == "__main__":
    from database import FoodDatabase
    db = FoodDatabase()
    alerts = AlertSystem(db)

    print("=== Current Alert Summary ===\n")
    print(alerts.generate_alert_summary())
    print("\n=== Statistics ===\n")
    print(alerts.get_statistics())
