# Analytics and statistics for food waste tracking

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any
from collections import defaultdict
from loguru import logger

from database import FoodDatabase, FoodItem

logger.add("logs/analytics.log", rotation="10 MB")

UTC = timezone.utc


class AnalyticsError(Exception):
    """Base exception for analytics-related errors"""
    pass


class FoodAnalytics:
    """Analytics engine for food waste and consumption patterns"""

    # Average cost per item (₹) - India-specific approximate values (2025-2026)
    FOOD_COSTS = {
        'dairy': 150,
        'fruits': 60,
        'vegetables': 40,
        'grains': 80,
        'proteins': 200,
        'beverages': 50,
        'snacks': 100,
        'other': 100
    }

    # CO₂ emissions (kg CO₂e per kg of food) - approximate lifecycle values
    CO2_EMISSIONS = {
        'dairy': 2.8,
        'fruits': 0.6,
        'vegetables': 0.3,
        'grains': 0.8,
        'proteins': 4.5,       # meat-heavy
        'beverages': 0.5,
        'snacks': 1.2,
        'other': 1.0
    }

    def __init__(self, database: FoodDatabase):
        self.db = database
        logger.info("FoodAnalytics initialized")

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def calculate_waste_statistics(self, days: int = 30) -> Dict[str, Any]:
        """
        Calculate key waste & consumption statistics for the given period.
        
        Returns:
            Dict with waste metrics
        """
        if days < 1:
            raise ValueError("Period must be at least 1 day")

        cutoff = self._now() - timedelta(days=days)

        # Fetch all relevant items (we'll filter in memory - acceptable for <10k items)
        wasted_items = self.db.get_all_items('wasted')
        consumed_items = self.db.get_all_items('consumed')
        shared_items = self.db.get_all_items('shared')

        def in_period(item: FoodItem) -> bool:
            return item.updated_at is not None and item.updated_at >= cutoff

        wasted = [item for item in wasted_items if in_period(item)]
        consumed = [item for item in consumed_items if in_period(item)]
        shared = [item for item in shared_items if in_period(item)]

        total_tracked = len(wasted) + len(consumed) + len(shared)
        waste_rate = (len(wasted) / total_tracked * 100) if total_tracked > 0 else 0.0

        waste_cost = sum(self._get_item_cost(item) for item in wasted)
        waste_co2 = sum(self._get_item_co2(item) for item in wasted)
        shared_cost = sum(self._get_item_cost(item) for item in shared)

        return {
            'period_days': days,
            'items_wasted': len(wasted),
            'items_consumed': len(consumed),
            'items_shared': len(shared),
            'total_items': total_tracked,
            'waste_rate_percent': round(waste_rate, 2),
            'estimated_cost_wasted': round(waste_cost, 2),
            'co2_kg_wasted': round(waste_co2, 2),
            'sharing_impact_items': len(shared),
            'sharing_impact_cost_saved': round(shared_cost, 2)
        }

    def get_monthly_breakdown(self) -> List[Dict[str, Any]]:
        """Monthly waste/consumption statistics (all-time)"""
        months = defaultdict(lambda: {'wasted': 0, 'consumed': 0, 'shared': 0, 'cost_wasted': 0.0})

        for status in ['wasted', 'consumed', 'shared']:
            items = self.db.get_all_items(status=status)
            for item in items:
                if item.updated_at:
                    month_key = item.updated_at.strftime('%Y-%m')
                    months[month_key][status] += 1
                    if status == 'wasted':
                        months[month_key]['cost_wasted'] += self._get_item_cost(item)

        result = []
        for month_key in sorted(months.keys()):
            data = months[month_key]
            total = data['wasted'] + data['consumed'] + data['shared']
            waste_rate = (data['wasted'] / total * 100) if total > 0 else 0.0

            result.append({
                'month': month_key,
                'wasted': data['wasted'],
                'consumed': data['consumed'],
                'shared': data['shared'],
                'total': total,
                'waste_rate_percent': round(waste_rate, 2),
                'cost_wasted_rupees': round(data['cost_wasted'], 2)
            })

        return result

    def get_category_analysis(self) -> Dict[str, Dict[str, Any]]:
        """Waste analysis grouped by category (all-time)"""
        categories = defaultdict(lambda: {'total': 0, 'wasted': 0, 'cost': 0.0})

        for status in ['wasted', 'consumed', 'shared']:
            items = self.db.get_all_items(status=status)
            for item in items:
                cat = (item.category or 'other').lower()
                categories[cat]['total'] += 1
                if status == 'wasted':
                    categories[cat]['wasted'] += 1
                    categories[cat]['cost'] += self._get_item_cost(item)

        result = {}
        for cat, data in categories.items():
            waste_rate = (data['wasted'] / data['total'] * 100) if data['total'] > 0 else 0.0
            result[cat] = {
                'total_items': data['total'],
                'wasted_items': data['wasted'],
                'waste_rate_percent': round(waste_rate, 2),
                'estimated_cost_wasted': round(data['cost'], 2)
            }

        return result

    def get_sustainability_impact(self) -> Dict[str, Any]:
        """Annual environmental & economic impact metrics"""
        annual_stats = self.calculate_waste_statistics(days=365)

        co2_kg = annual_stats['co2_kg_wasted']

        return {
            'annual_co2_wasted_kg': round(co2_kg, 2),
            'equivalent_car_miles': round(co2_kg / 0.41, 1),      # ~0.41 kg CO₂/mile (average car)
            'water_saved_liters': round(annual_stats['sharing_impact_items'] * 50),  # rough estimate
            'tree_planting_equivalent': round(co2_kg / 20, 1),   # ~20 kg CO₂/tree/year
            'annual_savings_currency': round(annual_stats['estimated_cost_wasted'], 2),
            'sdg_12_compliance': 'Good' if annual_stats['waste_rate_percent'] < 15 else 'Needs Improvement'
        }

    def predict_waste_items(self, days_ahead: int = 7) -> List[Dict[str, Any]]:
        """Predict items at high risk of waste in next N days"""
        now = self._now()
        active = self.db.get_all_items('active')

        at_risk = [
            item for item in active
            if item.expiry_date and 0 < (item.expiry_date - now).days <= days_ahead
        ]

        sorted_risk = sorted(
            at_risk,
            key=lambda x: (x.expiry_date - now).days if x.expiry_date else 999
        )

        result = []
        for item in sorted_risk:
            days_left = (item.expiry_date - now).days
            risk_score = max(0, min(100, (1 - days_left / days_ahead) * 100))

            result.append({
                'item_name': item.name,
                'category': item.category,
                'days_remaining': days_left,
                'risk_score': round(risk_score, 1),
                'estimated_cost': round(self._get_item_cost(item), 2),
                'recommendation': self._get_recommendation(days_left)
            })

        return result

    def get_user_insights(self) -> List[str]:
        """Generate human-readable, actionable insights"""
        insights = []

        stats_30d = self.calculate_waste_statistics(30)
        categories = self.get_category_analysis()

        # Waste rate feedback
        rate = stats_30d['waste_rate_percent']
        if rate > 20:
            insights.append(
                f"⚠️ Warning: Your waste rate is {rate}% over last 30 days. "
                "Consider better meal planning and FIFO (First In First Out)."
            )
        elif rate < 10:
            insights.append(
                f"🌟 Excellent! Only {rate}% waste rate in last 30 days. "
                "You're doing great for the planet!"
            )

        # Worst category
        if categories:
            worst = max(categories.items(), key=lambda x: x[1]['waste_rate_percent'])
            if worst[1]['waste_rate_percent'] > 30:
                insights.append(
                    f"🍎 {worst[0].title()} is your most wasted category "
                    f"({worst[1]['waste_rate_percent']}% waste rate). "
                    "Try buying smaller quantities or better storage."
                )

        # Sharing impact
        if stats_30d['items_shared'] > 0:
            insights.append(
                f"🤝 Well done! You shared {stats_30d['items_shared']} items "
                f"this month, saving ≈₹{stats_30d['sharing_impact_cost_saved']}"
            )

        # At-risk items warning
        risky = self.predict_waste_items(days_ahead=3)
        if len(risky) > 4:
            insights.append(
                f"📦 Urgent: {len(risky)} items are expiring in the next 3 days. "
                "Time to cook, freeze or share!"
            )

        return insights or ["✓ No major issues detected. Keep logging your items!"]

    def export_report(self, format: str = 'text') -> str:
        """Generate formatted report (text for now)"""
        stats = self.calculate_waste_statistics(30)
        impact = self.get_sustainability_impact()
        insights = self.get_user_insights()

        if format.lower() == 'text':
            lines = [
                "=" * 70,
                "FOOD WASTE & SUSTAINABILITY REPORT",
                f"Generated: {self._now().strftime('%Y-%m-%d %H:%M:%S')} UTC",
                "=" * 70,
                "",
                "📊 LAST 30 DAYS",
                "-" * 60,
                f"Total tracked items     : {stats['total_items']}",
                f"  → Consumed            : {stats['items_consumed']}",
                f"  → Shared              : {stats['items_shared']}",
                f"  → Wasted              : {stats['items_wasted']}",
                f"Waste rate              : {stats['waste_rate_percent']}%",
                f"Estimated cost wasted   : ₹{stats['estimated_cost_wasted']}",
                "",
                "🌍 ANNUAL ENVIRONMENTAL IMPACT",
                "-" * 60,
                f"CO₂ from waste          : {impact['annual_co2_wasted_kg']} kg",
                f"Equivalent car travel   : ~{impact['equivalent_car_miles']} miles",
                f"Water saved by sharing  : {impact['water_saved_liters']} liters",
                f"Trees needed to offset  : ~{impact['tree_planting_equivalent']}",
                "",
                "💡 ACTIONABLE INSIGHTS",
                "-" * 60
            ]

            for i, insight in enumerate(insights, 1):
                lines.append(f"{i}. {insight}")

            lines.extend([
                "",
                "=" * 70,
                "Keep tracking — every item logged helps fight food waste!",
                "=" * 70
            ])

            return "\n".join(lines)

        elif format.lower() == 'csv':
            return "CSV export not yet implemented"

        return "Unsupported format"

    @staticmethod
    def _get_item_cost(item: FoodItem) -> float:
        cat = (item.category or 'other').lower()
        return FoodAnalytics.FOOD_COSTS.get(cat, 100) * item.quantity

    @staticmethod
    def _get_item_co2(item: FoodItem) -> float:
        cat = (item.category or 'other').lower()
        return FoodAnalytics.CO2_EMISSIONS.get(cat, 1.0) * item.quantity

    @staticmethod
    def _get_recommendation(days_left: int) -> str:
        if days_left <= 1:
            return "Use TODAY or SHARE immediately!"
        if days_left <= 2:
            return "Plan to use very soon or freeze"
        if days_left <= 4:
            return "Prioritize this week"
        return "Still time to plan"


if __name__ == "__main__":
    db = FoodDatabase()
    analytics = FoodAnalytics(db)
    print(analytics.export_report())
