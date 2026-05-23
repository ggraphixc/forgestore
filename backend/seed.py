"""
Seed script: Populate the SQLite database with products, categories, retailers,
users, orders, reviews, and admin users.
Run: python seed.py
"""
import sys
import os
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

import io
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
elif hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

OK = "[OK]"
SKIP = "[--]"

# ─── Fixed UUIDs for reproducibility ─────────────────────────────────

def fixed_uuid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"forgestore-{name}"))

# ─── Data ────────────────────────────────────────────────────────────

RETAILERS = [
    {
        "id": fixed_uuid("retailer-1"),
        "name": "TechVault",
        "slug": "techvault",
        "bio": "Premium electronics and gadgets from trusted global brands. We source only authentic products.",
        "location": "Lagos, Nigeria",
        "primary_color": "blue",
        "rating": 4.8,
        "review_count": 142,
    },
    {
        "id": fixed_uuid("retailer-2"),
        "name": "StyleCraft",
        "slug": "stylecraft",
        "bio": "Curated fashion, home & living essentials. Elevate your everyday style.",
        "location": "Abuja, Nigeria",
        "primary_color": "amber",
        "rating": 4.6,
        "review_count": 98,
    },
]

CATEGORIES = [
    {"id": fixed_uuid("cat-electronics"), "name": "Electronics", "slug": "electronics",
     "description": "Latest tech innovations and gadgets"},
    {"id": fixed_uuid("cat-fashion"), "name": "Fashion", "slug": "fashion",
     "description": "Trending styles and timeless classics"},
    {"id": fixed_uuid("cat-home-living"), "name": "Home & Living", "slug": "home-living",
     "description": "Elevate your living space"},
    {"id": fixed_uuid("cat-sports"), "name": "Sports", "slug": "sports",
     "description": "Gear up for your active lifestyle"},
    {"id": fixed_uuid("cat-gaming"), "name": "Gaming", "slug": "gaming",
     "description": "Next-level gaming experiences"},
    {"id": fixed_uuid("cat-wellness"), "name": "Wellness", "slug": "wellness",
     "description": "Health and self-care essentials"},
    {"id": fixed_uuid("cat-beauty"), "name": "Beauty", "slug": "beauty",
     "description": "Premium skincare and cosmetics"},
    {"id": fixed_uuid("cat-automotive"), "name": "Automotive", "slug": "automotive",
     "description": "Car care and accessories"},
]

CAT_MAP = {c["slug"]: c["id"] for c in CATEGORIES}

PRODUCTS = [
    {"id": fixed_uuid("prd-iphone-16-pro-max"), "slug": "iphone-16-pro-max",
     "name": "iPhone 16 Pro Max", "brand": "Apple",
     "description": "The most powerful iPhone ever with breakthrough camera capabilities and all-day battery life.",
     "price": 1199, "discount_price": 1099, "images": ["/static/img/products/phone-1.jpg"],
     "category_id": CAT_MAP["electronics"], "retailer_id": RETAILERS[0]["id"],
     "inventory": 45, "rating": 4.8, "review_count": 234, "is_new_arrival": True,
     "sub_category": "Smartphones",
     "specifications": {"Display": '6.9" Super Retina XDR', "Chip": "A18 Pro", "Storage": "256GB", "Camera": "48MP Pro Camera", "Battery": "33 hours video"}},

    {"id": fixed_uuid("prd-galaxy-s25-ultra"), "slug": "galaxy-s25-ultra",
     "name": "Galaxy S25 Ultra", "brand": "Samsung",
     "description": "Ultimate productivity meets cutting-edge AI in Samsung's flagship powerhouse.",
     "price": 1299, "discount_price": None, "images": ["/static/img/products/phone-2.jpg"],
     "category_id": CAT_MAP["electronics"], "retailer_id": RETAILERS[0]["id"],
     "inventory": 32, "rating": 4.7, "review_count": 189, "is_new_arrival": True,
     "sub_category": "Smartphones",
     "specifications": {"Display": '6.9" Dynamic AMOLED', "Processor": "Snapdragon 8 Gen 4", "RAM": "12GB", "Storage": "512GB", "Camera": "200MP Quad Camera"}},

    {"id": fixed_uuid("prd-sony-wh1000xm6"), "slug": "sony-wh1000xm6",
     "name": "WH-1000XM6", "brand": "Sony",
     "description": "Experience industry-leading noise cancellation with exceptional sound quality.",
     "price": 399, "discount_price": None, "images": ["/static/img/products/headphones-1.jpg"],
     "category_id": CAT_MAP["electronics"], "retailer_id": RETAILERS[0]["id"],
     "inventory": 89, "rating": 4.9, "review_count": 312, "is_new_arrival": False,
     "sub_category": "Audio",
     "specifications": {"Type": "Over-Ear Wireless", "Noise Cancel": "Industry Leading", "Battery": "40 hours", "Bluetooth": "5.3", "Weight": "250g"}},

    {"id": fixed_uuid("prd-dell-xps-16"), "slug": "dell-xps-16",
     "name": "XPS 16 9640", "brand": "Dell",
     "description": "Professional-grade laptop with stunning OLED display and unmatched performance.",
     "price": 1899, "discount_price": None, "images": ["/static/img/products/laptop-1.jpg"],
     "category_id": CAT_MAP["electronics"], "retailer_id": RETAILERS[0]["id"],
     "inventory": 12, "rating": 4.6, "review_count": 156, "is_new_arrival": False,
     "sub_category": "Laptops",
     "specifications": {"Display": '16" 4K OLED', "Processor": "Intel Core Ultra 9", "RAM": "32GB LPDDR5X", "Storage": "2TB NVMe SSD", "GPU": "RTX 4070"}},

    {"id": fixed_uuid("prd-nike-air-max-dn"), "slug": "nike-air-max-dn",
     "name": "Air Max DN", "brand": "Nike",
     "description": "Revolutionary Air Max with dynamic air pockets that adapt to your stride.",
     "price": 170, "discount_price": 140, "images": ["/static/img/products/shoe-1.jpg"],
     "category_id": CAT_MAP["fashion"], "retailer_id": RETAILERS[1]["id"],
     "inventory": 200, "rating": 4.5, "review_count": 421, "is_new_arrival": True,
     "sub_category": "Footwear",
     "specifications": {"Style": "DV3331-002", "Color": "Black/White", "Material": "Synthetic Leather", "Sole": "Air Cushion", "Fit": "True to size"}},

    {"id": fixed_uuid("prd-adidas-ultraboost-light"), "slug": "adidas-ultraboost-light",
     "name": "Ultraboost Light", "brand": "Adidas",
     "description": "Lightest Ultraboost ever with incredible energy return for every run.",
     "price": 190, "discount_price": None, "images": ["/static/img/products/shoe-2.jpg"],
     "category_id": CAT_MAP["fashion"], "retailer_id": RETAILERS[1]["id"],
     "inventory": 156, "rating": 4.7, "review_count": 289, "is_new_arrival": False,
     "sub_category": "Footwear",
     "specifications": {"Model": "FY8472", "Color": "Core Black", "Weight": "266g", "Drop": "10mm", "Technology": "Boost Midsole"}},

    {"id": fixed_uuid("prd-levis-501-original"), "slug": "levis-501-original",
     "name": "501 Original Fit", "brand": "Levi's",
     "description": "The original blue jean since 1873. Classic straight fit that defines denim culture.",
     "price": 98, "discount_price": None, "images": ["/static/img/products/jeans-1.jpg"],
     "category_id": CAT_MAP["fashion"], "retailer_id": RETAILERS[1]["id"],
     "inventory": 300, "rating": 4.4, "review_count": 567, "is_new_arrival": False,
     "sub_category": "Clothing",
     "specifications": {"Fit": "Original Straight", "Material": "100% Cotton Denim", "Rise": "Mid Rise", "Closure": "Button Fly", "Care": "Machine Wash"}},

    {"id": fixed_uuid("prd-kitchenaid-stand-mixer-pro"), "slug": "kitchenaid-stand-mixer-pro",
     "name": "Stand Mixer Pro", "brand": "KitchenAid",
     "description": "Professional stand mixer that powers through any recipe with precision and style.",
     "price": 449, "discount_price": None, "images": ["/static/img/products/mixer-1.jpg"],
     "category_id": CAT_MAP["home-living"], "retailer_id": RETAILERS[1]["id"],
     "inventory": 67, "rating": 4.8, "review_count": 198, "is_new_arrival": False,
     "sub_category": "Kitchen",
     "specifications": {"Capacity": "6 Quart", "Power": "575 Watts", "Speeds": "10 Speed", "Bowl": "Stainless Steel", "Attachments": "Flat Beater, Dough Hook, Whisk"}},

    {"id": fixed_uuid("prd-dyson-v15-detect"), "slug": "dyson-v15-detect",
     "name": "V15 Detect", "brand": "Dyson",
     "description": "Laser reveals microscopic dust. Piezo sensor counts dust particles in real time.",
     "price": 749, "discount_price": 649, "images": ["/static/img/products/vacuum-1.jpg"],
     "category_id": CAT_MAP["home-living"], "retailer_id": RETAILERS[1]["id"],
     "inventory": 23, "rating": 4.9, "review_count": 145, "is_new_arrival": True,
     "sub_category": "Cleaning",
     "specifications": {"Type": "Cordless Vacuum", "Runtime": "60 minutes", "Suction": "230AW", "Dust Bin": "0.77L", "Weight": "6.8 lbs"}},

    {"id": fixed_uuid("prd-bose-quietcomfort-ultra"), "slug": "bose-quietcomfort-ultra",
     "name": "QuietComfort Ultra", "brand": "Bose",
     "description": "World-class noise cancellation with personalized sound optimization.",
     "price": 429, "discount_price": None, "images": ["/static/img/products/headphones-2.jpg"],
     "category_id": CAT_MAP["electronics"], "retailer_id": RETAILERS[0]["id"],
     "inventory": 78, "rating": 4.6, "review_count": 267, "is_new_arrival": False,
     "sub_category": "Audio",
     "specifications": {"Type": "Over-Ear Wireless", "Noise Cancel": "CustomTune Tech", "Battery": "24 hours", "Bluetooth": "5.3", "Spatial Audio": "Yes"}},

    {"id": fixed_uuid("prd-nike-yoga-mat-pro"), "slug": "nike-yoga-mat-pro",
     "name": "Yoga Mat Pro", "brand": "Nike",
     "description": "Premium yoga mat with superior grip and cushioning for every practice.",
     "price": 85, "discount_price": None, "images": ["/static/img/products/yoga-mat-1.jpg"],
     "category_id": CAT_MAP["sports"], "retailer_id": RETAILERS[1]["id"],
     "inventory": 0, "rating": 4.3, "review_count": 89, "is_new_arrival": False,
     "sub_category": "Fitness",
     "specifications": {"Material": "Eco-friendly TPE", "Thickness": "5mm", "Dimensions": '68" x 24"', "Weight": "2.5 lbs", "Texture": "Non-slip"}},

    {"id": fixed_uuid("prd-kitchenaid-air-fryer-8qt"), "slug": "kitchenaid-air-fryer-8qt",
     "name": "Air Fryer 8QT", "brand": "KitchenAid",
     "description": "Dual-basket air fryer for cooking two foods at different temperatures simultaneously.",
     "price": 199, "discount_price": None, "images": ["/static/img/products/air-fryer-1.jpg"],
     "category_id": CAT_MAP["home-living"], "retailer_id": RETAILERS[1]["id"],
     "inventory": 112, "rating": 4.5, "review_count": 176, "is_new_arrival": False,
     "sub_category": "Kitchen",
     "specifications": {"Capacity": "8 Quart", "Temperature": "170-400F", "Presets": "7 Cooking Presets", "Basket": "Dual Basket", "Wattage": "1700W"}},

    {"id": fixed_uuid("prd-ps5-pro"), "slug": "ps5-pro",
     "name": "PS5 Pro", "brand": "Sony",
     "description": "Next-gen console with advanced ray tracing and ultra-fast SSD loading.",
     "price": 699, "discount_price": None, "images": ["/static/img/products/ps5-1.jpg"],
     "category_id": CAT_MAP["gaming"], "retailer_id": RETAILERS[0]["id"],
     "inventory": 8, "rating": 4.8, "review_count": 98, "is_new_arrival": True,
     "sub_category": "Consoles",
     "specifications": {"GPU": "Custom RDNA 3", "CPU": "8-core Zen 4", "Storage": "2TB SSD", "Ray Tracing": "Hardware Accelerated", "Output": "8K Gaming"}},

    {"id": fixed_uuid("prd-samsung-galaxy-watch-7"), "slug": "samsung-galaxy-watch-7",
     "name": "Galaxy Watch 7", "brand": "Samsung",
     "description": "Advanced health monitoring with Galaxy AI coaching and enhanced battery life.",
     "price": 349, "discount_price": 299, "images": ["/static/img/products/watch-1.jpg"],
     "category_id": CAT_MAP["electronics"], "retailer_id": RETAILERS[0]["id"],
     "inventory": 144, "rating": 4.6, "review_count": 203, "is_new_arrival": True,
     "sub_category": "Wearables",
     "specifications": {"Display": '1.5" Super AMOLED', "Processor": "Exynos W1000", "Battery": "590mAh", "Health": "BioActive Sensor", "Water": "5ATM + IP68"}},

    {"id": fixed_uuid("prd-nordic-face-serum"), "slug": "nordic-face-serum",
     "name": "Nordic Face Serum", "brand": "Lumina",
     "description": "Intensive hydration serum with Nordic botanical extracts for radiant skin.",
     "price": 89, "discount_price": None, "images": ["/static/img/products/serum-1.jpg"],
     "category_id": CAT_MAP["beauty"], "retailer_id": RETAILERS[1]["id"],
     "inventory": 201, "rating": 4.7, "review_count": 312, "is_new_arrival": False,
     "sub_category": "Skincare",
     "specifications": {"Volume": "30ml", "Key Ingredient": "Hyaluronic Acid", "Skin Type": "All Types", "Results": "24h Hydration", "Cruelty Free": "Yes"}},

    {"id": fixed_uuid("prd-dyson-car-vacuum-2000"), "slug": "dyson-car-vacuum-2000",
     "name": "Car Vacuum 2000", "brand": "Dyson",
     "description": "Compact car vacuum with powerful suction for deep cleaning your vehicle.",
     "price": 299, "discount_price": None, "images": ["/static/img/products/car-vacuum-1.jpg"],
     "category_id": CAT_MAP["automotive"], "retailer_id": RETAILERS[0]["id"],
     "inventory": 55, "rating": 0, "review_count": 0, "is_new_arrival": False,
     "sub_category": "Car Care",
     "specifications": {"Type": "Portable Vacuum", "Runtime": "20 minutes", "Suction": "120AW", "Weight": "1.5kg", "Accessories": "4 Tools"}},

    {"id": fixed_uuid("prd-nike-pro-basketball"), "slug": "nike-pro-basketball",
     "name": "Pro Basketball", "brand": "Nike",
     "description": "Official size basketball with superior grip and durability for competitive play.",
     "price": 65, "discount_price": None, "images": ["/static/img/products/basketball-1.jpg"],
     "category_id": CAT_MAP["sports"], "retailer_id": RETAILERS[1]["id"],
     "inventory": 178, "rating": 4.5, "review_count": 67, "is_new_arrival": False,
     "sub_category": "Team Sports",
     "specifications": {"Size": "Official Size 7", "Material": "Composite Leather", "Grip": "Deep Channel", "Inflation": "8.5 PSI", "Usage": "Indoor/Outdoor"}},

    {"id": fixed_uuid("prd-samsung-smart-scale-p3"), "slug": "samsung-smart-scale-p3",
     "name": "Smart Scale P3", "brand": "Samsung",
     "description": "Advanced body composition scale with smartphone integration and detailed metrics.",
     "price": 129, "discount_price": None, "images": ["/static/img/products/scale-1.jpg"],
     "category_id": CAT_MAP["wellness"], "retailer_id": RETAILERS[0]["id"],
     "inventory": 91, "rating": 4.4, "review_count": 134, "is_new_arrival": False,
     "sub_category": "Health Monitoring",
     "specifications": {"Metrics": "Weight, BMI, Body Fat", "Connectivity": "Bluetooth 5.0", "Users": "Up to 16", "Display": "LCD Backlit", "App": "Samsung Health"}},

    {"id": fixed_uuid("prd-gaming-mouse-x"), "slug": "gaming-mouse-x",
     "name": "Gaming Mouse X", "brand": "Sony",
     "description": "Ultra-precise gaming mouse with customizable RGB lighting and programmable buttons.",
     "price": 159, "discount_price": None, "images": ["/static/img/products/mouse-1.jpg"],
     "category_id": CAT_MAP["gaming"], "retailer_id": RETAILERS[0]["id"],
     "inventory": 123, "rating": 4.6, "review_count": 178, "is_new_arrival": False,
     "sub_category": "Gaming Accessories",
     "specifications": {"Sensor": "PAW3950", "DPI": "26000", "Buttons": "8 Programmable", "Polling Rate": "1000Hz", "RGB": "16.8M Colors"}},

    {"id": fixed_uuid("prd-silk-pillowcase-set"), "slug": "silk-pillowcase-set",
     "name": "Silk Pillowcase Set", "brand": "Home Luxe",
     "description": "Luxurious mulberry silk pillowcases for better skin and hair health.",
     "price": 79, "discount_price": None, "images": ["/static/img/products/pillowcase-1.jpg"],
     "category_id": CAT_MAP["home-living"], "retailer_id": RETAILERS[1]["id"],
     "inventory": 267, "rating": 4.8, "review_count": 245, "is_new_arrival": False,
     "sub_category": "Bedding",
     "specifications": {"Material": "22 Momme Mulberry Silk", "Size": "Standard/Queen", "Pieces": "2 Pillowcases", "Closure": "Envelope", "Care": "Hand Wash"}},
]

USERS = [
    {"id": fixed_uuid("user-alice"), "email": "alice@example.com", "name": "Alice Cooper", "password": None},
    {"id": fixed_uuid("user-john"), "email": "john@example.com", "name": "John Doe", "password": None},
    {"id": fixed_uuid("user-sarah"), "email": "sarah@example.com", "name": "Sarah Miller", "password": None},
    {"id": fixed_uuid("user-mike"), "email": "mike@example.com", "name": "Mike Wilson", "password": None},
    {"id": fixed_uuid("user-emily"), "email": "emily@example.com", "name": "Emily Chen", "password": None},
    {"id": fixed_uuid("user-david"), "email": "david@example.com", "name": "David Brown", "password": None},
    {"id": fixed_uuid("user-lisa"), "email": "lisa@example.com", "name": "Lisa Park", "password": None},
    {"id": fixed_uuid("user-james"), "email": "james@example.com", "name": "James Taylor", "password": None},
    {"id": fixed_uuid("user-emma"), "email": "emma@example.com", "name": "Emma Davis", "password": None},
    {"id": fixed_uuid("user-robert"), "email": "robert@example.com", "name": "Robert Garcia", "password": None},
]

PROD_MAP = {p["slug"]: p["id"] for p in PRODUCTS}

ORDERS = [
    {"id": fixed_uuid("order-1"), "order_number": "ORD-8821", "status": "PENDING",
     "total_amount": 1099, "customer_id": USERS[0]["id"],
     "shipping_address": {"street": "123 Main St", "city": "New York", "state": "NY", "country": "USA", "zip": "10001"}},
    {"id": fixed_uuid("order-2"), "order_number": "ORD-8822", "status": "SHIPPED",
     "total_amount": 470, "customer_id": USERS[1]["id"],
     "shipping_address": {"street": "456 Oak Ave", "city": "Los Angeles", "state": "CA", "country": "USA", "zip": "90001"}},
    {"id": fixed_uuid("order-3"), "order_number": "ORD-8823", "status": "DELIVERED",
     "total_amount": 648, "customer_id": USERS[2]["id"],
     "shipping_address": {"street": "789 Pine Rd", "city": "Chicago", "state": "IL", "country": "USA", "zip": "60601"}},
    {"id": fixed_uuid("order-4"), "order_number": "ORD-8824", "status": "PROCESSING",
     "total_amount": 1598, "customer_id": USERS[3]["id"],
     "shipping_address": {"street": "321 Elm St", "city": "Austin", "state": "TX", "country": "USA", "zip": "73301"}},
    {"id": fixed_uuid("order-5"), "order_number": "ORD-8825", "status": "PENDING",
     "total_amount": 798, "customer_id": USERS[4]["id"],
     "shipping_address": {"street": "654 Maple Dr", "city": "Seattle", "state": "WA", "country": "USA", "zip": "98101"}},
    {"id": fixed_uuid("order-6"), "order_number": "ORD-8826", "status": "SHIPPED",
     "total_amount": 723, "customer_id": USERS[5]["id"],
     "shipping_address": {"street": "987 Cedar Ln", "city": "Miami", "state": "FL", "country": "USA", "zip": "33101"}},
    {"id": fixed_uuid("order-7"), "order_number": "ORD-8827", "status": "DELIVERED",
     "total_amount": 1899, "customer_id": USERS[6]["id"],
     "shipping_address": {"street": "147 Birch Blvd", "city": "Boston", "state": "MA", "country": "USA", "zip": "02101"}},
    {"id": fixed_uuid("order-8"), "order_number": "ORD-8828", "status": "PROCESSING",
     "total_amount": 858, "customer_id": USERS[7]["id"],
     "shipping_address": {"street": "258 Spruce St", "city": "Denver", "state": "CO", "country": "USA", "zip": "80201"}},
    {"id": fixed_uuid("order-9"), "order_number": "ORD-8829", "status": "CANCELLED",
     "total_amount": 649, "customer_id": USERS[8]["id"],
     "shipping_address": {"street": "369 Willow Way", "city": "Portland", "state": "OR", "country": "USA", "zip": "97201"}},
    {"id": fixed_uuid("order-10"), "order_number": "ORD-8830", "status": "DELIVERED",
     "total_amount": 425, "customer_id": USERS[0]["id"],
     "shipping_address": {"street": "123 Main St", "city": "New York", "state": "NY", "country": "USA", "zip": "10001"}},
    {"id": fixed_uuid("order-11"), "order_number": "ORD-8831", "status": "SHIPPED",
     "total_amount": 325, "customer_id": USERS[1]["id"],
     "shipping_address": {"street": "456 Oak Ave", "city": "Los Angeles", "state": "CA", "country": "USA", "zip": "90001"}},
    {"id": fixed_uuid("order-12"), "order_number": "ORD-8832", "status": "PENDING",
     "total_amount": 269, "customer_id": USERS[2]["id"],
     "shipping_address": {"street": "789 Pine Rd", "city": "Chicago", "state": "IL", "country": "USA", "zip": "60601"}},
    {"id": fixed_uuid("order-13"), "order_number": "ORD-8833", "status": "PROCESSING",
     "total_amount": 2198, "customer_id": USERS[3]["id"],
     "shipping_address": {"street": "321 Elm St", "city": "Austin", "state": "TX", "country": "USA", "zip": "73301"}},
    {"id": fixed_uuid("order-14"), "order_number": "ORD-8834", "status": "DELIVERED",
     "total_amount": 797, "customer_id": USERS[4]["id"],
     "shipping_address": {"street": "654 Maple Dr", "city": "Seattle", "state": "WA", "country": "USA", "zip": "98101"}},
    {"id": fixed_uuid("order-15"), "order_number": "ORD-8835", "status": "SHIPPED",
     "total_amount": 576, "customer_id": USERS[5]["id"],
     "shipping_address": {"street": "987 Cedar Ln", "city": "Miami", "state": "FL", "country": "USA", "zip": "33101"}},
]

ORDER_ITEMS = [
    {"id": fixed_uuid("oi-1"), "order_id": fixed_uuid("order-1"), "product_id": PROD_MAP["iphone-16-pro-max"], "price": 1099, "quantity": 1},
    {"id": fixed_uuid("oi-2"), "order_id": fixed_uuid("order-2"), "product_id": PROD_MAP["nike-air-max-dn"], "price": 140, "quantity": 2},
    {"id": fixed_uuid("oi-3"), "order_id": fixed_uuid("order-2"), "product_id": PROD_MAP["adidas-ultraboost-light"], "price": 190, "quantity": 1},
    {"id": fixed_uuid("oi-4"), "order_id": fixed_uuid("order-3"), "product_id": PROD_MAP["kitchenaid-stand-mixer-pro"], "price": 449, "quantity": 1},
    {"id": fixed_uuid("oi-5"), "order_id": fixed_uuid("order-3"), "product_id": PROD_MAP["kitchenaid-air-fryer-8qt"], "price": 199, "quantity": 1},
    {"id": fixed_uuid("oi-6"), "order_id": fixed_uuid("order-4"), "product_id": PROD_MAP["galaxy-s25-ultra"], "price": 1299, "quantity": 1},
    {"id": fixed_uuid("oi-7"), "order_id": fixed_uuid("order-4"), "product_id": PROD_MAP["samsung-galaxy-watch-7"], "price": 299, "quantity": 1},
    {"id": fixed_uuid("oi-8"), "order_id": fixed_uuid("order-5"), "product_id": PROD_MAP["sony-wh1000xm6"], "price": 399, "quantity": 2},
    {"id": fixed_uuid("oi-9"), "order_id": fixed_uuid("order-6"), "product_id": PROD_MAP["bose-quietcomfort-ultra"], "price": 429, "quantity": 1},
    {"id": fixed_uuid("oi-10"), "order_id": fixed_uuid("order-6"), "product_id": PROD_MAP["levis-501-original"], "price": 98, "quantity": 3},
    {"id": fixed_uuid("oi-11"), "order_id": fixed_uuid("order-7"), "product_id": PROD_MAP["dell-xps-16"], "price": 1899, "quantity": 1},
    {"id": fixed_uuid("oi-12"), "order_id": fixed_uuid("order-8"), "product_id": PROD_MAP["ps5-pro"], "price": 699, "quantity": 1},
    {"id": fixed_uuid("oi-13"), "order_id": fixed_uuid("order-8"), "product_id": PROD_MAP["gaming-mouse-x"], "price": 159, "quantity": 1},
    {"id": fixed_uuid("oi-14"), "order_id": fixed_uuid("order-9"), "product_id": PROD_MAP["dyson-v15-detect"], "price": 649, "quantity": 1},
    {"id": fixed_uuid("oi-15"), "order_id": fixed_uuid("order-10"), "product_id": PROD_MAP["nordic-face-serum"], "price": 89, "quantity": 3},
    {"id": fixed_uuid("oi-16"), "order_id": fixed_uuid("order-10"), "product_id": PROD_MAP["silk-pillowcase-set"], "price": 79, "quantity": 2},
    {"id": fixed_uuid("oi-17"), "order_id": fixed_uuid("order-11"), "product_id": PROD_MAP["nike-pro-basketball"], "price": 65, "quantity": 5},
    {"id": fixed_uuid("oi-18"), "order_id": fixed_uuid("order-12"), "product_id": PROD_MAP["samsung-smart-scale-p3"], "price": 129, "quantity": 1},
    {"id": fixed_uuid("oi-19"), "order_id": fixed_uuid("order-12"), "product_id": PROD_MAP["nike-air-max-dn"], "price": 140, "quantity": 1},
    {"id": fixed_uuid("oi-20"), "order_id": fixed_uuid("order-13"), "product_id": PROD_MAP["iphone-16-pro-max"], "price": 1099, "quantity": 2},
    {"id": fixed_uuid("oi-21"), "order_id": fixed_uuid("order-14"), "product_id": PROD_MAP["samsung-galaxy-watch-7"], "price": 299, "quantity": 2},
    {"id": fixed_uuid("oi-22"), "order_id": fixed_uuid("order-14"), "product_id": PROD_MAP["kitchenaid-air-fryer-8qt"], "price": 199, "quantity": 1},
    {"id": fixed_uuid("oi-23"), "order_id": fixed_uuid("order-15"), "product_id": PROD_MAP["adidas-ultraboost-light"], "price": 190, "quantity": 2},
    {"id": fixed_uuid("oi-24"), "order_id": fixed_uuid("order-15"), "product_id": PROD_MAP["levis-501-original"], "price": 98, "quantity": 2},
]

REVIEWS = [
    {"id": fixed_uuid("rev-1"), "product_id": PROD_MAP["iphone-16-pro-max"], "author": "Alex Johnson",
     "rating": 5, "title": "Worth every penny!", "helpful": 24,
     "content": "The camera system is incredible. Night mode shots look like daylight. Battery easily lasts all day with heavy use."},
    {"id": fixed_uuid("rev-2"), "product_id": PROD_MAP["iphone-16-pro-max"], "author": "Maria Garcia",
     "rating": 4, "title": "Great phone, but heavy", "helpful": 18,
     "content": "Amazing display and performance. Only complaint is the weight - it's noticeable in a pocket. Otherwise perfect."},
    {"id": fixed_uuid("rev-3"), "product_id": PROD_MAP["nike-air-max-dn"], "author": "Chris Lee",
     "rating": 5, "title": "Best Air Max ever", "helpful": 32,
     "content": "The dynamic air pockets actually make a difference. Most comfortable sneakers I've owned. Highly recommend!"},
    {"id": fixed_uuid("rev-4"), "product_id": PROD_MAP["nike-air-max-dn"], "author": "Jordan Smith",
     "rating": 4, "title": "Great look, runs large", "helpful": 15,
     "content": "Love the design and comfort. They run about half a size large, so order accordingly. Great value on sale."},
    {"id": fixed_uuid("rev-5"), "product_id": PROD_MAP["kitchenaid-stand-mixer-pro"], "author": "Taylor Wright",
     "rating": 5, "title": "Kitchen game changer", "helpful": 41,
     "content": "This mixer handles everything from delicate meringues to heavy bread dough with ease. The 6-quart bowl is perfect for large batches."},
    {"id": fixed_uuid("rev-6"), "product_id": PROD_MAP["dyson-v15-detect"], "author": "Morgan Chen",
     "rating": 5, "title": "Laser dust detection is amazing", "helpful": 28,
     "content": "Seeing the dust you can't see with the naked eye is eye-opening. Incredible suction power and the hair screw tool is fantastic."},
    {"id": fixed_uuid("rev-7"), "product_id": PROD_MAP["ps5-pro"], "author": "Riley Park",
     "rating": 5, "title": "Next-gen gaming perfection", "helpful": 19,
     "content": "Ray tracing is mind-blowing. Load times are instant with the SSD. Worth upgrading from base PS5."},
    {"id": fixed_uuid("rev-8"), "product_id": PROD_MAP["nordic-face-serum"], "author": "Avery Kim",
     "rating": 5, "title": "Skin transformed in 2 weeks", "helpful": 36,
     "content": "My skin has never looked better. Fine lines are reduced and hydration is on point. A little goes a long way."},
    {"id": fixed_uuid("rev-9"), "product_id": PROD_MAP["silk-pillowcase-set"], "author": "Jamie Rivera",
     "rating": 5, "title": "Game changer for hair health", "helpful": 22,
     "content": "After switching to these silk pillowcases, my hair is so much less frizzy in the morning. The quality is exceptional."},
    {"id": fixed_uuid("rev-10"), "product_id": PROD_MAP["sony-wh1000xm6"], "author": "Sam Patel",
     "rating": 5, "title": "Best noise cancellation on the market", "helpful": 37,
     "content": "These headphones are incredible. The noise cancellation is so good I nearly missed my train stop. Sound quality is superb."},
]


# ─── Seed Logic ──────────────────────────────────────────────────────

def seed_database():
    from app.database import SessionLocal, engine, Base
    from app.models import (
        Retailer, Category, Product, User, Order, OrderItem, Review,
        AdminUser, AdminRole, OrderStatus
    )
    from app.auth import hash_password

    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # ── 1. Retailers ──
        print(f"\n{'='*50}")
        print("  Seeding Retailers...")
        print(f"{'='*50}")
        for r in RETAILERS:
            existing = db.query(Retailer).filter(Retailer.slug == r["slug"]).first()
            if not existing:
                retailer = Retailer(**r)
                db.add(retailer)
                print(f"{OK} Created: {r['name']}")
            else:
                print(f"{SKIP} Exists: {r['name']}")
        db.flush()

        # ── 2. Categories ──
        print(f"\n{'='*50}")
        print("  Seeding Categories...")
        print(f"{'='*50}")
        for c in CATEGORIES:
            existing = db.query(Category).filter(Category.slug == c["slug"]).first()
            if not existing:
                cat = Category(**c)
                db.add(cat)
                print(f"{OK} Created: {c['name']}")
            else:
                print(f"{SKIP} Exists: {c['name']}")
        db.flush()

        # ── 3. Products ──
        print(f"\n{'='*50}")
        print("  Seeding Products...")
        print(f"{'='*50}")
        for p in PRODUCTS:
            existing = db.query(Product).filter(Product.slug == p["slug"]).first()
            if not existing:
                prod = Product(**p)
                db.add(prod)
                print(f"{OK} Created: {p['name']}")
            else:
                print(f"{SKIP} Exists: {p['name']}")
        db.flush()

        # ── 4. Users ──
        print(f"\n{'='*50}")
        print("  Seeding Users...")
        print(f"{'='*50}")
        for u in USERS:
            existing = db.query(User).filter(User.email == u["email"]).first()
            if not existing:
                user = User(**u)
                db.add(user)
                print(f"{OK} Created: {u['email']}")
            else:
                print(f"{SKIP} Exists: {u['email']}")
        db.flush()

        # ── 5. Orders ──
        print(f"\n{'='*50}")
        print("  Seeding Orders...")
        print(f"{'='*50}")
        for o in ORDERS:
            existing = db.query(Order).filter(Order.order_number == o["order_number"]).first()
            if not existing:
                order = Order(
                    id=o["id"],
                    order_number=o["order_number"],
                    status=OrderStatus(o["status"]),
                    total_amount=o["total_amount"],
                    shipping_address=o["shipping_address"],
                    customer_id=o["customer_id"],
                )
                db.add(order)
                print(f"{OK} Created: {o['order_number']}")
            else:
                print(f"{SKIP} Exists: {o['order_number']}")
        db.flush()

        # ── 6. Order Items ──
        print(f"\n{'='*50}")
        print("  Seeding Order Items...")
        print(f"{'='*50}")
        for oi in ORDER_ITEMS:
            existing = db.query(OrderItem).filter(OrderItem.id == oi["id"]).first()
            if not existing:
                item = OrderItem(**oi)
                db.add(item)
                print(f"{OK} Created: {oi['id']}")
            else:
                print(f"{SKIP} Exists: {oi['id']}")
        db.flush()

        # ── 7. Reviews ──
        print(f"\n{'='*50}")
        print("  Seeding Reviews...")
        print(f"{'='*50}")
        for r in REVIEWS:
            existing = db.query(Review).filter(Review.id == r["id"]).first()
            if not existing:
                review = Review(**r, user_id=None)
                db.add(review)
                print(f"{OK} Created: Review by {r['author']}")
            else:
                print(f"{SKIP} Exists: Review by {r['author']}")
        db.flush()

        # ── 8. Admin User ──
        print(f"\n{'='*50}")
        print("  Seeding Admin Users...")
        print(f"{'='*50}")
        admin_email = "admin@forgestore.com"
        existing_admin = db.query(AdminUser).filter(AdminUser.email == admin_email).first()
        if not existing_admin:
            admin = AdminUser(
                id=fixed_uuid("admin-forgestore"),
                email=admin_email,
                password=hash_password("admin123"),
                name="Admin",
                role=AdminRole.DIR_ADMIN,
            )
            db.add(admin)
            print(f"{OK} Created: {admin_email} / admin123")
        else:
            print(f"{SKIP} Exists: {admin_email}")

        # ── 9. Commit ──
        db.commit()
        print(f"\n{'='*50}")
        print(f"  ✅ Seeding complete!")
        print(f"  {len(PRODUCTS)} products, {len(CATEGORIES)} categories,")
        print(f"  {len(RETAILERS)} retailers, {len(USERS)} users,")
        print(f"  {len(ORDERS)} orders, {len(REVIEWS)} reviews")
        print(f"{'='*50}")

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Seed failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


def run_settings_seed():
    """Run the settings seeder after main seed completes."""
    print(f"\n{'='*50}")
    print("  Seeding Settings...")
    print(f"{'='*50}")
    try:
        from seed_settings import seed_settings
        seed_settings()
    except Exception as e:
        print(f"[ERROR] Settings seed failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    seed_database()
    run_settings_seed()
    print("\n[OK] All seeding complete.")
