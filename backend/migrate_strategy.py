from app.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text('ALTER TABLE "order" ADD COLUMN fulfillment_mode VARCHAR(20) DEFAULT \'VENDOR\''))
        conn.commit()
        print("OK: fulfillment_mode -> order")
    except Exception as e:
        if "duplicate column" in str(e).lower():
            print("EXISTS: fulfillment_mode on order")
        else:
            print(f"ERR: {e}")
        conn.rollback()
