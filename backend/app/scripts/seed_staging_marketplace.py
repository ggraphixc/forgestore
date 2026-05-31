"""
Production Staging Seeder — populates a clean multi-vendor testing environment.

Usage:
    python -m app.scripts.seed_staging_marketplace

Creates:
  - 1 DIR_ADMIN master profile
  - 3 Vendor profiles with isolated wallets
  - 10 multi-category test products across vendors
  - All mandatory SystemSetting key-values
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.database import Base, get_engine, SessionLocal
from app.models import (
    AdminUser, AdminRole, Retailer, Product, Category,
    VendorWallet, VendorWalletTransaction, Settings,
    User, Order, OrderItem, OrderStatus,
)
from app.auth import hash_password
from app.services.ai_service import SETTINGS_DEFINITIONS
from app.utils import utcnow

import uuid


def _uuid():
    return str(uuid.uuid4())


def seed():
    """Run the staging seed."""
    engine = get_engine()
    db = SessionLocal()

    print("=" * 60)
    print("  FORGESTORE — PRODUCTION STAGING SEEDER")
    print("=" * 60)

    # ── Step 0: Run migration 007 to ensure schema is current ──
    print("\n[0/5] Running schema migration 007...")
    try:
        from migrations import run_migration
        run_migration.run_migration("007")
    except Exception as e:
        print(f"      Migration 007: {e}")

    # ── Step 1: Wipe staging data tables ──
    print("\n[1/5] Clearing staging data...")
    try:
        db.query(OrderItem).delete()
        db.query(Order).delete()
        db.query(Product).delete()
        db.query(VendorWalletTransaction).delete()
        db.query(VendorWallet).delete()
        db.query(Retailer).delete()
        db.query(User).delete()
        db.commit()
        print("      Cleared: orders, products, retailers, wallets, users")
    except Exception as e:
        db.rollback()
        print(f"      Warning during cleanup: {e}")
        db.rollback()

    # ── Step 2: Seed SystemSettings ──
    print("\n[2/5] Seeding SystemSettings...")
    settings_count = 0
    for sd in SETTINGS_DEFINITIONS:
        existing = db.query(Settings).filter(Settings.key == sd["key"]).first()
        if not existing:
            s = Settings(
                key=sd["key"],
                value=sd.get("default", ""),
                category=sd["category"],
                setting_type=sd["type"],
                label=sd["label"],
                description=sd.get("description", ""),
            )
            db.add(s)
            settings_count += 1
    db.commit()
    print(f"      Created {settings_count} new settings ({len(SETTINGS_DEFINITIONS)} total defined)")

    # ── Step 3: Create DIR_ADMIN ──
    print("\n[3/5] Creating DIR_ADMIN master account...")
    admin = db.query(AdminUser).filter(AdminUser.email == "admin@forgestore.com").first()
    if not admin:
        admin = AdminUser(
            id=_uuid(),
            email="admin@forgestore.com",
            password=hash_password("admin123"),
            name="Master Admin",
            role=AdminRole.DIR_ADMIN,
        )
        db.add(admin)
        db.commit()
        print("      Created: admin@forgestore.com / admin123")
    else:
        print("      DIR_ADMIN already exists, skipping")

    # ── Step 4: Create 3 Vendor profiles with wallets ──
    print("\n[4/5] Creating vendor profiles...")
    vendor_data = [
        {"name": "Lagos Crafts Co.", "slug": "lagos-crafts", "bio": "Premium handcrafted goods from Lagos", "email": "vendor1@forgestore.com"},
        {"name": "Abuja Fashion House", "slug": "abuja-fashion", "bio": "Contemporary Nigerian fashion", "email": "vendor2@forgestore.com"},
        {"name": "PH Electronics Hub", "slug": "ph-electronics", "bio": "Latest electronics and gadgets", "email": "vendor3@forgestore.com"},
    ]

    vendors = []
    for vd in vendor_data:
        existing = db.query(Retailer).filter(Retailer.slug == vd["slug"]).first()
        if existing:
            vendors.append(existing)
            print(f"      {vd['name']} — already exists, skipping")
            continue

        retailer = Retailer(
            id=_uuid(),
            name=vd["name"],
            slug=vd["slug"],
            bio=vd["bio"],
            status="ACTIVE",
            rating=4.5,
            review_count=0,
            commission_rate=10.0,
        )
        db.add(retailer)
        db.flush()

        # Create vendor admin user
        vendor_admin = AdminUser(
            id=_uuid(),
            email=vd["email"],
            password=hash_password("vendor123"),
            name=vd["name"],
            role=AdminRole.RETAILER,
            vendor_id=retailer.id,
        )
        db.add(vendor_admin)

        # Create vendor wallet
        wallet = VendorWallet(
            id=_uuid(),
            retailer_id=retailer.id,
            balance=0.0,
            pending_balance=0.0,
            locked_escrow_balance=0.0,
            currency="NGN",
            status="ACTIVE",
        )
        db.add(wallet)

        vendors.append(retailer)
        print(f"      Created: {vd['name']} (admin: {vd['email']} / vendor123)")

    db.commit()

    # ── Step 5: Create 10 test products across vendors ──
    print("\n[5/5] Creating test products...")

    # Create categories
    cat_data = [
        ("Handmade", "handmade", "Artisan handmade goods"),
        ("Fashion", "fashion", "Clothing and accessories"),
        ("Electronics", "electronics", "Electronic devices and gadgets"),
        ("Home & Living", "home-living", "Home decor and furniture"),
    ]
    cats = {}
    for cname, cslug, cdesc in cat_data:
        existing = db.query(Category).filter(Category.slug == cslug).first()
        if existing:
            cats[cslug] = existing
        else:
            cat = Category(id=_uuid(), name=cname, slug=cslug, description=cdesc)
            db.add(cat)
            db.flush()
            cats[cslug] = cat

    product_data = [
        # Vendor 0: Lagos Crafts
        {"name": "Handwoven Basket", "slug": "handwoven-basket", "price": 15000, "cat": "handmade", "vendor_idx": 0, "inv": 25},
        {"name": "Adire Scarf", "slug": "adire-scarf", "price": 8500, "cat": "handmade", "vendor_idx": 0, "inv": 40},
        {"name": "Carved Wooden Bowl", "slug": "carved-wooden-bowl", "price": 22000, "cat": "handmade", "vendor_idx": 0, "inv": 15},
        # Vendor 1: Abuja Fashion
        {"name": "Ankara Maxi Dress", "slug": "ankara-maxi-dress", "price": 35000, "cat": "fashion", "vendor_idx": 1, "inv": 20},
        {"name": "Male Kaftan Set", "slug": "male-kaftan-set", "price": 45000, "cat": "fashion", "vendor_idx": 1, "inv": 18},
        {"name": "Leather Crossbody Bag", "slug": "leather-crossbody-bag", "price": 28000, "cat": "fashion", "vendor_idx": 1, "inv": 30},
        # Vendor 2: PH Electronics
        {"name": "Wireless Earbuds Pro", "slug": "wireless-earbuds-pro", "price": 25000, "cat": "electronics", "vendor_idx": 2, "inv": 50},
        {"name": "Smart Watch X1", "slug": "smart-watch-x1", "price": 42000, "cat": "electronics", "vendor_idx": 2, "inv": 35},
        {"name": "Portable Bluetooth Speaker", "slug": "bluetooth-speaker", "price": 18000, "cat": "electronics", "vendor_idx": 2, "inv": 45},
        # Cross-vendor: Home item from Vendor 0
        {"name": "Raffia Table Runner", "slug": "raffia-table-runner", "price": 12000, "cat": "home-living", "vendor_idx": 0, "inv": 60},
    ]

    created_products = 0
    for pd in product_data:
        existing = db.query(Product).filter(Product.slug == pd["slug"]).first()
        if existing:
            continue

        product = Product(
            id=_uuid(),
            name=pd["name"],
            slug=pd["slug"],
            description=f"Premium quality {pd['name'].lower()} from our collection.",
            price=pd["price"],
            inventory=pd["inv"],
            retailer_id=vendors[pd["vendor_idx"]].id,
            category_id=cats[pd["cat"]].id,
            images=["/static/img/placeholder.svg"],
            rating=0.0,
            review_count=0,
            is_new_arrival=True,
        )
        db.add(product)
        created_products += 1

    db.commit()

    # Summary
    total_retailers = db.query(Retailer).count()
    total_products = db.query(Product).count()
    total_wallets = db.query(VendorWallet).count()
    total_settings = db.query(Settings).count()
    total_admins = db.query(AdminUser).count()

    print("\n" + "=" * 60)
    print("  SEED COMPLETE")
    print("=" * 60)
    print(f"  Admin Users:    {total_admins}")
    print(f"  Vendors:        {total_retailers}")
    print(f"  Products:       {total_products}")
    print(f"  Vendor Wallets: {total_wallets}")
    print(f"  Settings:       {total_settings}")
    print(f"\n  Admin Login:    admin@forgestore.com / admin123")
    print(f"  Vendor Logins:  vendor1@forgestore.com, vendor2@forgestore.com, vendor3@forgestore.com")
    print(f"                  Password: vendor123")
    print("=" * 60)

    db.close()


if __name__ == "__main__":
    seed()
