"""Verify phone column exists on user table."""
import asyncio
import asyncpg

DATABASE_URL = "postgresql://forgestore:npg_9UDHopLBZ0lX@ep-fragrant-queen-a7k49o71-pooler.ap-southeast-2.aws.neon.tech/eCommerce?sslmode=require&channel_binding=require"

async def run():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'user' AND column_name = 'phone'
            )
        """)
        print(f"phone column exists: {exists}")
    finally:
        await conn.close()

asyncio.run(run())
