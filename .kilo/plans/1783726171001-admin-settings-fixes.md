# Admin Settings System Fixes

## Problem
14 gaps in the admin settings system across 3 layers: definitions (`ai_service.py`), DB (`models.py`), API (`admin_api.py`), template (`index.html`), and middleware (`main.py`).

## Prioritized Fix Plan

### Phase 1: Core Quick Wins (no DB migration needed)

#### 1. Add `json` type handler in template
**File**: `backend/app/templates/admin/settings/index.html`
- Add `{% elif s.type == 'json' %}` branch alongside existing type handlers
- Render as a `<textarea>` with `font-family: ui-monospace` (already styled for textarea)
- On save, stringify/parse JSON client-side; server stores as string (consistent with current `value` column)
- Prefix template value with `JSON.parse()` hint or auto-format on blur

#### 2. Add `/api/admin/upload` endpoint
**File**: `backend/app/routers/admin_api.py`
- Add `@router.post("/upload")` that accepts `UploadFile`
- Use existing `cloudinary_upload.upload_to_cloudinary()` or local `compress_image()` + static path
- Return `{"urls": [url]}` to match the template's expectation at `index.html:707`
- Gate behind `require_role("settings")`

#### 3. Add validation in settings API
**File**: `backend/app/routers/admin_api.py`
- In `_get_setting_def`, return the full definition dict (already available)
- In `update_setting` and `bulk_update_settings`, before saving:
  - `number` type: parse to float/int, reject non-numeric with `HTTPException(400)`
  - `select` type: validate value is in `sd["options"]` list
  - Use setting `default` as fallback if value is empty string and field is required
- Add `min`/`max` support to `SETTINGS_DEFINITIONS` if present (future-proofing)

#### 4. Seed defaults on startup
**File**: `backend/app/main.py` (startup sequence)
- After migrations run, add: for each entry in `SETTINGS_DEFINITIONS`, if key not in DB, insert with `default` value
- Use `IGNORE` or existence check to avoid duplicate inserts
- This ensures `get_categorized_settings()` always returns full set, not partial

#### 5. Add current values to search filter
**File**: `backend/app/templates/admin/settings/index.html`
- Extend `data-search` attribute to include `s.value` (current setting value)
- Change line 612 from `{{ s.label|lower }} {{ s.key|lower }} {{ s.description|default('', true)|lower }}` to also append `{{ s.value|lower }}`
- This lets admins search for "NGN" and find the currency setting

#### 6. Add confirmation dialogs for destructive settings
**File**: `backend/app/templates/admin/settings/index.html`
- Define a set of `data-confirm` attributes on fields with keys: `maintenance_mode`, `market_commission_percentage`, `vendor_minimum_rating`, `default_shipping_fee`
- Add a JS `confirmSettingChange(key, label)` function
- Before saving, check for confirmations; use `window.confirm` with descriptive message

---

### Phase 2: Safety & Audit (low risk, additive)

#### 7. Enforce maintenance_mode middleware
**File**: `backend/app/main.py`
- Add a FastAPI `Middleware` class `MaintenanceModeMiddleware`
- On every request, check `get_site_settings(db)` for `maintenance_mode == "true"`
- If enabled and request is not from an authenticated admin, return 503 with a maintenance template
- Need to handle async DB session — use `request.state.db` or create a scoped session

**File**: `backend/app/templates/admin/base.html` or new `backend/app/templates/maintenance.html`
- Simple maintenance page template shown to non-admins

#### 8. Add settings diff to audit log
**File**: `backend/app/routers/admin_api.py`
- In `update_setting` and `bulk_update_settings`, capture `old_value` before update
- Format diff as `"maintenance_mode: false → true"` or `"site_name: 'Old' → 'New'"`
- Include in `log_admin_action` details string
- For bulk updates, aggregate diffs: `"Updated 5 settings: site_name: 'A'→'B', ..."`

#### 9. Add revert/rollback capability
**Files**: `backend/app/models.py`, `backend/app/routers/admin_api.py`
- New model `SettingsHistory` (or `SettingsAudit`): `id`, `setting_key`, `old_value`, `new_value`, `changed_by_admin_id`, `changed_at`
- In `update_setting`, insert a `SettingsHistory` row before each change
- New API endpoint: `GET /api/admin/settings/history/{key}` returns last 50 changes
- New template section or modal: show history with "Revert" button per row
- Revert endpoint: `POST /api/admin/settings/{key}/revert` restores the previous value

**Alternative (simpler)**: Reuse `AdminAuditLog` which already records actions. Add a `revert` action type that looks up the last change. This avoids a new model.

#### 10. Differentiate permissions per category
**Files**: `backend/app/services/ai_service.py`, `backend/app/routers/admin_api.py`, `backend/app/routers/admin.py`
- Change `SETTINGS_CATEGORY_PERMISSIONS` to map each category to a distinct permission string:
  - `global` → `settings_global`
  - `design` → `settings_design`
  - `technical` → `settings_technical`
  - `optional` → `settings_optional`
  - `developer` → `settings_developer`
  - `logistics` → `settings_logistics`
  - `other` → `settings_other`
- In `admin.py:516-524`, compute `accessible_categories` per-category instead of blanket `has_permission(admin, "settings")`
- In `admin_api.py:651-653`, check the specific category permission
- Backward compat: keep `has_permission(admin, "settings")` as a super-permission that grants access to all categories

---

### Phase 3: Structural Improvements

#### 11. Resolve `mail_console_fallback` dual source
**File**: `backend/app/services/ai_service.py`
- Remove `mail_console_fallback` from `SETTINGS_DEFINITIONS` (it's already a Pydantic env var in `config.py`)
- The env var `MAIL_CONSOLE_FALLBACK` is the single source of truth
- Any code reading it via `get_site_settings(db)` should be updated to use `get_settings().mail_console_fallback`
- This eliminates the divergence risk

**File**: `backend/app/core/email.py` and any other consumers
- Audit all references to `mail_console_fallback` and route through `get_settings()`

#### 12. Populate `Settings.options` from definitions
**File**: `backend/app/routers/admin_api.py` (in `update_setting` / `bulk_update_settings`)
- When creating a new `Settings` row, populate `options` from `sd.get("options")` if present
- This makes the DB row self-contained — useful for export, external tools, or if `SETTINGS_DEFINITIONS` changes
- No template change needed currently, but sets up for future dynamic option editing

#### 13. Add settings import/export
**File**: `backend/app/routers/admin_api.py`
- `GET /api/admin/settings/export` — returns JSON of all current settings (key, value, category, label)
- `POST /api/admin/settings/import` — accepts JSON array or object, upserts each setting, logs admin action
- Add UI buttons in `admin/settings/index.html`: "Export Settings" (downloads JSON), "Import Settings" (file input + confirm)

---

### Out of Scope (explicitly deferred)
- **#14 Multi-webhook URLs**: Single webhook is current design. Multi-webhook requires new `WebhookEndpoint` model, delivery fan-out, retry logic. Defer to separate effort.
- **Granular per-field validation**: Min/max bounds are future-proofed in definitions but not wired into all 50+ settings. Current fix covers type-level validation only.
- **Settings versioning/snapshots**: Full versioning is overkill. History + revert (item #9) is sufficient.

---

## Validation Plan

1. **Startup seeding**: After fix #4, verify `Settings` table has all ~50 keys on fresh DB. Check `get_categorized_settings()` returns same count as `SETTINGS_DEFINITIONS`.
2. **Template rendering**: Verify all 7 type branches render: text, select, boolean, password, textarea, number, file, json.
3. **Upload flow**: Test logo/favicon upload end-to-end — upload → `/api/admin/upload` → Cloudinary/local → URL stored in setting → template renders preview.
4. **Validation**: Try saving "abc" to `inventory_threshold` — should return 400 with clear error.
5. **Maintenance mode**: Enable via settings, verify non-admin requests get 503, admin requests pass through.
6. **Permissions**: Create admin with only `settings_global` permission — verify they can only edit Global tab, not Design/Technical.
7. **Audit diff**: Change a setting, check `AdminAuditLog.details` contains `"key: old → new"`.
8. **Revert**: Change a value, click revert, verify DB value restored and history entry created.
9. **Import/export**: Export all settings, modify JSON, import back, verify changes applied.

## Files Changed

| File | Changes |
|------|---------|
| `backend/app/templates/admin/settings/index.html` | Items #1, #5, #6, #13 |
| `backend/app/routers/admin_api.py` | Items #2, #3, #4, #8, #9, #10, #12, #13 |
| `backend/app/main.py` | Items #4 (seed), #7 (middleware) |
| `backend/app/services/ai_service.py` | Items #10 (remove dual source), #11 (permissions) |
| `backend/app/templates/maintenance.html` | Item #7 (new file) |
| `backend/app/core/email.py` | Item #10 (routing fix) |
