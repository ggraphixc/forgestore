#!/usr/bin/env bash
# ============================================
#  ForgeStore Backend — Unix Start Script
# ============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  ╔═══════════════════════════════════════╗"
echo "  ║       ForgeStore Backend Server       ║"
echo "  ╚═══════════════════════════════════════╝"
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "  [!] WARNING: .env file not found."
    echo "      Create backend/.env with your Paystack secret key:"
    echo "      PAYSTACK_SECRET_KEY=sk_live_xxxxxxxxxxxx"
    echo ""
    sleep 2
fi

# Install dependencies if needed
echo "  [*] Checking dependencies..."
pip install -r requirements.txt -q 2>/dev/null || {
    echo "  [ERROR] Failed to install dependencies."
    echo "         Make sure pip is installed and try again."
    exit 1
}

# Seed database if forgestore.db does not exist
if [ ! -f "forgestore.db" ]; then
    echo "  [*] Seeding database with demo data..."
    python seed.py || {
        echo "  [ERROR] Database seeding failed."
        exit 1
    }
fi

# Start the server
echo "  [*] Starting server on http://127.0.0.1:8080"
echo "  [*] API docs at http://127.0.0.1:8080/docs"
echo "  [*] Press Ctrl+C to stop"
echo ""

exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
