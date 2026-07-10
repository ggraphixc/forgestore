"""Migration: Create ReturnRequest + ReturnEvent tables.

These tables are also created by Base.metadata.create_all() in init_db(),
so this script is only needed for manual migration on existing databases.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine
from app.models import Base

def migrate():
    print("Creating ReturnRequest + ReturnEvent tables via create_all...")
    Base.metadata.create_all(bind=engine)
    print("Done. Tables created if they didn't exist.")

if __name__ == "__main__":
    migrate()
