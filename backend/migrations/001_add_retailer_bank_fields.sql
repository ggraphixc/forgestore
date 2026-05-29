-- =============================================================================
-- Migration 001: Add Retailer Bank Fields & AdCampaign Table
-- Target: PostgreSQL
-- Run: psql -U <user> -d <dbname> -f 001_add_retailer_bank_fields.sql
-- =============================================================================

-- Step 1: Add banking/payment columns to retailer table
ALTER TABLE retailer
  ADD COLUMN IF NOT EXISTS bank_name VARCHAR(255),
  ADD COLUMN IF NOT EXISTS account_number VARCHAR(50),
  ADD COLUMN IF NOT EXISTS bank_code VARCHAR(20),
  ADD COLUMN IF NOT EXISTS account_name VARCHAR(255),
  ADD COLUMN IF NOT EXISTS paystack_subaccount_code VARCHAR(100),
  ADD COLUMN IF NOT EXISTS flutterwave_subaccount_id VARCHAR(100),
  ADD COLUMN IF NOT EXISTS commission_rate FLOAT NOT NULL DEFAULT 10.0;

-- Step 2: Create ad_campaign table
CREATE TABLE IF NOT EXISTS ad_campaign (
    id VARCHAR PRIMARY KEY,
    retailer_id VARCHAR NOT NULL REFERENCES retailer(id) ON DELETE CASCADE,
    product_id VARCHAR REFERENCES product(id) ON DELETE SET NULL,
    ad_type VARCHAR(20) NOT NULL DEFAULT 'SHOP',
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    banner_url VARCHAR,
    start_date TIMESTAMP,
    end_date TIMESTAMP,
    payment_reference VARCHAR(255) NOT NULL UNIQUE,
    clicks INTEGER NOT NULL DEFAULT 0,
    impressions INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Step 3: Create index on ad_campaign for common queries
CREATE INDEX IF NOT EXISTS idx_ad_campaign_retailer ON ad_campaign(retailer_id);
CREATE INDEX IF NOT EXISTS idx_ad_campaign_status ON ad_campaign(status);
CREATE INDEX IF NOT EXISTS idx_ad_campaign_payment_ref ON ad_campaign(payment_reference);
