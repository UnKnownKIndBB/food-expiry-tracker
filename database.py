# Database management for food inventory
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
from loguru import logger

logger.add("logs/database.log", rotation="10 MB")

UTC = timezone.utc


class DatabaseError(Exception):
    """Base exception for all database-related errors"""
    pass


@dataclass
class FoodItem:
    """Data class representing a food item in inventory"""
    id: Optional[int] = None
    name: str = ""
    category: str = ""
    purchase_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    quantity: float = 1.0
    unit: str = "units"
    location: str = "Refrigerator"
    status: str = "active"  # active, expired, consumed, wasted, shared, deleted
    ocr_confidence: float = 0.0
    image_path: Optional[str] = None
    notes: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FoodDatabase:
    """SQLite database manager for food waste & expiry tracking"""

    def __init__(self, db_path: str = "data/database.db"):
        self.db_path = db_path
        self.connection: Optional[sqlite3.Connection] = None
        self._connect()
        self._create_tables()
        logger.info(f"Database initialized at {db_path}")

    def _connect(self) -> None:
        """Establish connection with row factory"""
        try:
            self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self.connection.row_factory = sqlite3.Row
            logger.debug("Database connection established")
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to connect to database {self.db_path}: {e}") from e

    def _create_tables(self) -> None:
        """Create all required tables if they don't exist"""
        if not self.connection:
            raise DatabaseError("No active database connection")

        cursor = self.connection.cursor()

        # Food items
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS food_items (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                category        TEXT,
                purchase_date   TEXT,
                expiry_date     TEXT NOT NULL,
                quantity        REAL,
                unit            TEXT,
                location        TEXT,
                status          TEXT DEFAULT 'active',
                ocr_confidence  REAL,
                image_path      TEXT,
                notes           TEXT,
                created_at      TEXT,
                updated_at      TEXT
            )
        ''')

        # Alerts
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                food_item_id    INTEGER NOT NULL,
                alert_type      TEXT,
                triggered_date  TEXT,
                days_remaining  INTEGER,
                sent_to_user    BOOLEAN DEFAULT 0,
                FOREIGN KEY (food_item_id) REFERENCES food_items(id) ON DELETE CASCADE
            )
        ''')

        # Food sharing
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS food_sharing (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                food_item_id    INTEGER NOT NULL,
                posted_date     TEXT,
                shared_with     TEXT,
                shared_date     TEXT,
                latitude        REAL,
                longitude       REAL,
                pickup_location TEXT,
                status          TEXT DEFAULT 'available',
                FOREIGN KEY (food_item_id) REFERENCES food_items(id) ON DELETE CASCADE
            )
        ''')

        # Monthly statistics
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS statistics (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                month           TEXT UNIQUE NOT NULL,
                items_consumed  INTEGER DEFAULT 0,
                items_wasted    INTEGER DEFAULT 0,
                items_shared    INTEGER DEFAULT 0,
                estimated_savings REAL DEFAULT 0.0,
                co2_saved_kg    REAL DEFAULT 0.0
            )
        ''')

        self.connection.commit()
        logger.info("Database schema created/verified")

    def _normalize_name(self, name: str) -> str:
        """Normalize food item name before saving"""
        cleaned = (name or "").strip()
        if not cleaned:
            raise ValueError("Food name cannot be empty")
        return cleaned  # You may also do .lower() if you want case-insensitive dedup

    def add_food_item(self, food: FoodItem) -> int:
        """Insert new food item - returns new ID"""
        if not self.connection:
            raise DatabaseError("No active connection")

        try:
            cursor = self.connection.cursor()

            food.name = self._normalize_name(food.name)

            now = datetime.now(UTC).isoformat()

            cursor.execute('''
                INSERT INTO food_items (
                    name, category, purchase_date, expiry_date, quantity, unit,
                    location, status, ocr_confidence, image_path, notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                food.name,
                food.category,
                food.purchase_date.isoformat() if food.purchase_date else None,
                food.expiry_date.isoformat() if food.expiry_date else None,
                food.quantity,
                food.unit,
                food.location,
                food.status,
                food.ocr_confidence,
                food.image_path,
                food.notes,
                now,
                now
            ))

            self.connection.commit()
            item_id = cursor.lastrowid
            logger.info(f"Food item added: {food.name!r} (ID: {item_id})")
            return item_id

        except (sqlite3.Error, ValueError) as e:
            self.connection.rollback()
            raise DatabaseError(f"Failed to add food item '{food.name}': {e}") from e

    def get_all_items(self, status: str = "active") -> List[FoodItem]:
        """Get all items with given status, sorted by expiry"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                '''
                SELECT * FROM food_items
                WHERE status = ?
                ORDER BY expiry_date ASC
                ''',
                (status,)
            )
            return [self._row_to_fooditem(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get items (status={status}): {e}") from e

    def get_item_by_id(self, item_id: int) -> Optional[FoodItem]:
        """Fetch single item by ID"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM food_items WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            return self._row_to_fooditem(row) if row else None
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to fetch item ID {item_id}: {e}") from e

    def get_expiring_items(self, days: int = 7) -> List[FoodItem]:
        """Items expiring in the next N days (active only)"""
        try:
            cursor = self.connection.cursor()
            now = datetime.now(UTC)
            cutoff = (now + timedelta(days=days)).isoformat()
            now_iso = now.isoformat()

            cursor.execute(
                '''
                SELECT * FROM food_items
                WHERE status = 'active'
                  AND expiry_date <= ?
                  AND expiry_date > ?
                ORDER BY expiry_date ASC
                ''',
                (cutoff, now_iso)
            )
            return [self._row_to_fooditem(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to fetch expiring items ({days}d): {e}") from e

    # ──────────────────────────────────────────────────────────────────────────────
    # Other methods (update, delete, status, alerts, sharing) follow similar pattern
    # ──────────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_fooditem(row: sqlite3.Row) -> FoodItem:
        """Convert sqlite3.Row → FoodItem with proper datetime parsing"""
        def parse_iso(field: Optional[str]) -> Optional[datetime]:
            if not field:
                return None
            # Handle both Z and +00:00 formats
            dt_str = field.replace('Z', '+00:00')
            return datetime.fromisoformat(dt_str)

        return FoodItem(
            id=row['id'],
            name=row['name'],
            category=row['category'],
            purchase_date=parse_iso(row['purchase_date']),
            expiry_date=parse_iso(row['expiry_date']),
            quantity=row['quantity'],
            unit=row['unit'],
            location=row['location'],
            status=row['status'],
            ocr_confidence=row['ocr_confidence'],
            image_path=row['image_path'],
            notes=row['notes'],
            created_at=parse_iso(row['created_at']),
            updated_at=parse_iso(row['updated_at'])
        )

    def close(self) -> None:
        """Close database connection cleanly"""
        if self.connection:
            try:
                self.connection.close()
                logger.info("Database connection closed")
            finally:
                self.connection = None

    def __del__(self):
        self.close()


if __name__ == "__main__":
    # Quick smoke test
    db = FoodDatabase(":memory:")
    item = FoodItem(
        name="Test Milk",
        category="dairy",
        expiry_date=datetime.now(UTC) + timedelta(days=5)
    )
    db.add_food_item(item)
    print("Test item added successfully")
    db.close()       
