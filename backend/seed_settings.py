"""
Seed script: Populate default site settings with categories.
Run: python seed_settings.py
"""
import sys
import os
import sqlalchemy
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal, engine, Base
from app.models import Settings
from app.services.ai_service import SETTINGS_DEFINITIONS

import sys
import io

# Force UTF-8 for stdout
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
elif hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

OK = "[OK]"
SKIP = "[--]"


def ensure_columns():
    """Add new columns if they don't exist (for upgrades)."""
    import sqlite3
    db_path = os.path.join(os.path.dirname(__file__), "forgestore.db")
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    # Check existing columns
    c.execute("PRAGMA table_info(settings)")
    cols = {row[1] for row in c.fetchall()}
    additions = {
        "category": "ALTER TABLE settings ADD COLUMN category VARCHAR(50) DEFAULT 'other'",
        "setting_type": "ALTER TABLE settings ADD COLUMN setting_type VARCHAR(50) DEFAULT 'text'",
        "label": "ALTER TABLE settings ADD COLUMN label VARCHAR(255)",
        "description": "ALTER TABLE settings ADD COLUMN description TEXT",
        "options": "ALTER TABLE settings ADD COLUMN options TEXT",
    }
    for col_name, sql in additions.items():
        if col_name not in cols:
            try:
                c.execute(sql)
                print(f"{OK} Added column: {col_name}")
            except Exception as e:
                print(f"{SKIP} Column {col_name}: {e}")
    conn.commit()
    conn.close()


def seed_settings():
    # First, ensure new columns exist
    ensure_columns()
    
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        count = 0
        for sd in SETTINGS_DEFINITIONS:
            existing = db.query(Settings).filter(Settings.key == sd["key"]).first()
            if existing:
                changed = False
                if hasattr(existing, 'category') and not existing.category:
                    existing.category = sd["category"]
                    changed = True
                if hasattr(existing, 'setting_type') and not existing.setting_type:
                    existing.setting_type = sd["type"]
                    changed = True
                if hasattr(existing, 'label') and not existing.label:
                    existing.label = sd["label"]
                    changed = True
                if hasattr(existing, 'description') and not existing.description and sd.get("description"):
                    existing.description = sd["description"]
                    changed = True
                if changed:
                    print(f"{OK} Updated: {sd['key']}")
                    count += 1
                else:
                    print(f"{SKIP} Exists: {sd['key']}")
            else:
                setting = Settings(
                    key=sd["key"],
                    value=sd.get("default", ""),
                    category=sd["category"],
                    setting_type=sd["type"],
                    label=sd["label"],
                    description=sd.get("description", ""),
                )
                db.add(setting)
                print(f"{OK} Created: {sd['key']} [{sd['category']}]")
                count += 1

        db.commit()
        print(f"\n{OK} Done! {count} settings processed.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_settings()
