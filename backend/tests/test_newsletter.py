"""
Tests for newsletter CSV import and subscriber management endpoints.
"""

import io
import csv
import pytest
from app.auth import create_access_token


class TestNewsletterCSVImport:
    """CSV import endpoint tests."""

    IMPORT_URL = "/api/admin/newsletter-subscribers/import"
    LIST_URL = "/api/admin/newsletter-subscribers"

    def _admin_headers(self, admin_user):
        """Generate admin auth headers using direct token creation (avoids rate limiting)."""
        token = create_access_token({
            "sub": admin_user.id,
            "email": admin_user.email,
            "role": admin_user.role.value,
            "type": "admin",
        })
        return {"Authorization": f"Bearer {token}"}

    def _make_csv_file(self, rows, filename="test.csv"):
        """Helper: create an in-memory CSV file (BytesIO) from a list of dict rows."""
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        else:
            output.write("Email,Tags,Confirmed\r\n")
        csv_bytes = output.getvalue().encode("utf-8")
        return filename, csv_bytes, "text/csv"

    # --- Successful import ---

    def test_import_valid_csv(self, client, admin_user):
        """A valid CSV with new emails imports all rows successfully."""
        headers = self._admin_headers(admin_user)

        rows = [
            {"Email": "alice@example.com", "Tags": "vip", "Confirmed": "Yes"},
            {"Email": "bob@example.com", "Tags": "new", "Confirmed": "No"},
            {"Email": "carol@example.com", "Tags": "", "Confirmed": "Yes"},
        ]
        fname, fbytes, ftype = self._make_csv_file(rows)

        resp = client.post(
            self.IMPORT_URL,
            files={"file": (fname, fbytes, ftype)},
            headers=headers,
        )
        assert resp.status_code == 200, f"Import failed: {resp.text}"
        data = resp.json()
        assert data["total"] == 3
        assert data["imported"] == 3
        assert data["duplicates"] == 0
        assert data["errors"] == 0

        # Verify subscribers were created
        list_resp = client.get(self.LIST_URL, headers=headers)
        subscribers = list_resp.json()["subscribers"]
        emails = [s["email"] for s in subscribers]
        assert "alice@example.com" in emails
        assert "bob@example.com" in emails
        assert "carol@example.com" in emails

    # --- Duplicate detection ---

    def test_import_duplicates(self, client, admin_user):
        """Existing emails are reported as duplicates and not re-imported."""
        headers = self._admin_headers(admin_user)

        # Import Alice first time
        rows1 = [{"Email": "alice@example.com", "Tags": "vip", "Confirmed": "Yes"}]
        fname, fbytes, ftype = self._make_csv_file(rows1)
        r1 = client.post(self.IMPORT_URL, files={"file": (fname, fbytes, ftype)}, headers=headers)
        assert r1.status_code == 200
        assert r1.json()["imported"] == 1

        # Import Alice again (should be duplicate)
        rows2 = [
            {"Email": "alice@example.com", "Tags": "vip", "Confirmed": "Yes"},
            {"Email": "dave@example.com", "Tags": "new", "Confirmed": "No"},
        ]
        fname2, fbytes2, ftype2 = self._make_csv_file(rows2)
        r2 = client.post(self.IMPORT_URL, files={"file": (fname2, fbytes2, ftype2)}, headers=headers)
        assert r2.status_code == 200
        data = r2.json()
        assert data["total"] == 2
        assert data["imported"] == 1  # only dave
        assert data["duplicates"] == 1  # alice already exists
        assert "alice@example.com" in data["duplicate_emails"]
        assert data["errors"] == 0

    def test_import_self_duplicate_within_file(self, client, admin_user):
        """Duplicate emails within the same file are only imported once."""
        headers = self._admin_headers(admin_user)

        rows = [
            {"Email": "eve@example.com", "Tags": "vip", "Confirmed": "Yes"},
            {"Email": "eve@example.com", "Tags": "new", "Confirmed": "No"},  # same email
        ]
        fname, fbytes, ftype = self._make_csv_file(rows)
        resp = client.post(self.IMPORT_URL, files={"file": (fname, fbytes, ftype)}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["imported"] == 1
        assert data["duplicates"] == 1

    # --- Validation ---

    def test_import_missing_email_cell(self, client, admin_user):
        """Rows with missing emails are reported as errors."""
        headers = self._admin_headers(admin_user)

        rows = [
            {"Email": "", "Tags": "vip", "Confirmed": "Yes"},
            {"Email": "frank@example.com", "Tags": "", "Confirmed": "No"},
        ]
        fname, fbytes, ftype = self._make_csv_file(rows)
        resp = client.post(self.IMPORT_URL, files={"file": (fname, fbytes, ftype)}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["imported"] == 1
        assert data["errors"] == 1
        assert len(data["error_details"]) == 1
        assert "Missing email" in data["error_details"][0]

    def test_import_invalid_email(self, client, admin_user):
        """Invalid email formats are reported as errors."""
        headers = self._admin_headers(admin_user)

        rows = [
            {"Email": "not-an-email", "Tags": "", "Confirmed": ""},
            {"Email": "missing@dot", "Tags": "", "Confirmed": ""},
        ]
        fname, fbytes, ftype = self._make_csv_file(rows)
        resp = client.post(self.IMPORT_URL, files={"file": (fname, fbytes, ftype)}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["imported"] == 0
        assert data["errors"] == 2
        assert all("Invalid email" in e for e in data["error_details"])

    def test_import_missing_email_column(self, client, admin_user):
        """CSV without an Email column returns 400 with a helpful message."""
        headers = self._admin_headers(admin_user)

        rows = [{"Name": "Alice", "Country": "US"}]
        fname, fbytes, ftype = self._make_csv_file(rows)
        resp = client.post(self.IMPORT_URL, files={"file": (fname, fbytes, ftype)}, headers=headers)
        assert resp.status_code == 400
        assert "Email" in resp.json()["detail"]
        assert "Name" in resp.json()["detail"]

    def test_import_empty_csv(self, client, admin_user):
        """An empty CSV returns 400."""
        headers = self._admin_headers(admin_user)

        fname, fbytes, ftype = self._make_csv_file([], filename="empty.csv")
        resp = client.post(self.IMPORT_URL, files={"file": (fname, fbytes, ftype)}, headers=headers)
        assert resp.status_code == 400
        assert "no data rows" in resp.json()["detail"].lower()

    def test_import_non_csv_file(self, client, admin_user):
        """A non-CSV file returns 400."""
        headers = self._admin_headers(admin_user)

        resp = client.post(
            self.IMPORT_URL,
            files={"file": ("data.txt", b"hello world", "text/plain")},
            headers=headers,
        )
        assert resp.status_code == 400
        assert ".csv" in resp.json()["detail"].lower()

    def test_import_no_file(self, client, admin_user):
        """Request without a file returns 400."""
        headers = self._admin_headers(admin_user)

        resp = client.post(self.IMPORT_URL, headers=headers)
        assert resp.status_code == 400
        assert "CSV file is required" in resp.json()["detail"]

    # --- Tags and confirmed parsing ---

    def test_import_tags_parsing(self, client, admin_user):
        """Tags are correctly parsed from comma, semicolon, or pipe separators."""
        headers = self._admin_headers(admin_user)

        rows = [
            {"Email": "grace@example.com", "Tags": "vip, repeat", "Confirmed": "Yes"},
            {"Email": "heidi@example.com", "Tags": "wholesale; partner", "Confirmed": ""},
            {"Email": "ivan@example.com", "Tags": "one|two|three", "Confirmed": "1"},
        ]
        fname, fbytes, ftype = self._make_csv_file(rows)
        resp = client.post(self.IMPORT_URL, files={"file": (fname, fbytes, ftype)}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["imported"] == 3

        list_resp = client.get(self.LIST_URL, headers=headers)
        subs = {s["email"]: s for s in list_resp.json()["subscribers"]}

        assert subs["grace@example.com"]["tags"] == ["vip", "repeat"]
        assert subs["heidi@example.com"]["tags"] == ["wholesale", "partner"]
        assert subs["ivan@example.com"]["tags"] == ["one", "two", "three"]

    def test_import_confirmed_parsing(self, client, admin_user):
        """Confirmed column accepts yes/true/1/y/confirmed values."""
        headers = self._admin_headers(admin_user)

        rows = [
            {"Email": "jack@example.com", "Tags": "", "Confirmed": "yes"},
            {"Email": "kate@example.com", "Tags": "", "Confirmed": "true"},
            {"Email": "leo@example.com", "Tags": "", "Confirmed": "1"},
            {"Email": "mia@example.com", "Tags": "", "Confirmed": "Y"},
            {"Email": "nick@example.com", "Tags": "", "Confirmed": "confirmed"},
            {"Email": "olivia@example.com", "Tags": "", "Confirmed": "no"},
            {"Email": "paul@example.com", "Tags": "", "Confirmed": ""},
        ]
        fname, fbytes, ftype = self._make_csv_file(rows)
        resp = client.post(self.IMPORT_URL, files={"file": (fname, fbytes, ftype)}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["imported"] == 7

        list_resp = client.get(self.LIST_URL, headers=headers)
        subs = {s["email"]: s for s in list_resp.json()["subscribers"]}

        assert subs["jack@example.com"]["confirmed"] is True
        assert subs["kate@example.com"]["confirmed"] is True
        assert subs["leo@example.com"]["confirmed"] is True
        assert subs["mia@example.com"]["confirmed"] is True
        assert subs["nick@example.com"]["confirmed"] is True
        assert subs["olivia@example.com"]["confirmed"] is False
        assert subs["paul@example.com"]["confirmed"] is False

    def test_import_column_case_insensitivity(self, client, admin_user):
        """Column names are matched case-insensitively."""
        headers = self._admin_headers(admin_user)

        # Manually construct CSV with different case columns across rows
        # csv.DictWriter can't handle different keys per row, so build raw CSV
        csv_lines = [
            "EMAIL,TAGS,CONFIRMED",
            "quinn@example.com,vip,YES",
        ]
        csv_bytes = "\r\n".join(csv_lines).encode("utf-8")
        resp = client.post(
            self.IMPORT_URL,
            files={"file": ("test.csv", csv_bytes, "text/csv")},
            headers=headers,
        )
        assert resp.status_code == 200, f"UPPER case headers failed: {resp.text}"
        assert resp.json()["imported"] == 1

        # Test lowercase 'e-mail' header variant
        csv_lines2 = [
            "e-mail,tags,confirmed",
            "rachel@example.com,new,no",
        ]
        csv_bytes2 = "\r\n".join(csv_lines2).encode("utf-8")
        resp2 = client.post(
            self.IMPORT_URL,
            files={"file": ("test2.csv", csv_bytes2, "text/csv")},
            headers=headers,
        )
        assert resp2.status_code == 200, f"Lower case e-mail header failed: {resp2.text}"
        assert resp2.json()["imported"] == 1

    # --- Error CSV in response ---

    def test_import_error_csv_in_response(self, client, admin_user):
        """The response includes a downloadable_error_csv field when there are errors/duplicates."""
        headers = self._admin_headers(admin_user)

        rows = [
            {"Email": "sam@example.com", "Tags": "vip", "Confirmed": "Yes"},
            {"Email": "", "Tags": "", "Confirmed": ""},
            {"Email": "bad-email", "Tags": "", "Confirmed": ""},
        ]
        fname, fbytes, ftype = self._make_csv_file(rows)
        resp = client.post(self.IMPORT_URL, files={"file": (fname, fbytes, ftype)}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["imported"] == 1
        assert data["errors"] == 2
        assert data["downloadable_error_csv"] is not None
        assert "Missing email" in data["downloadable_error_csv"]
        assert "Invalid email format" in data["downloadable_error_csv"]
        assert "sam@example.com" not in data["downloadable_error_csv"]  # imported rows excluded

    def test_import_no_error_csv_when_clean(self, client, admin_user):
        """downloadable_error_csv is None when there are no errors or duplicates."""
        headers = self._admin_headers(admin_user)

        rows = [{"Email": "tina@example.com", "Tags": "", "Confirmed": "Yes"}]
        fname, fbytes, ftype = self._make_csv_file(rows)
        resp = client.post(self.IMPORT_URL, files={"file": (fname, fbytes, ftype)}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 1
        assert data["errors"] == 0
        assert data["duplicates"] == 0
        assert data["downloadable_error_csv"] is None

    # --- Sample CSV download ---

    def test_import_sample_csv_download(self, client, admin_user):
        """The sample CSV endpoint returns a valid CSV file."""
        headers = self._admin_headers(admin_user)
        resp = client.get("/api/admin/newsletter-subscribers/import/sample-csv", headers=headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in resp.headers.get("content-disposition", "")
        body = resp.text
        assert "Email" in body
        assert "Name" in body
        assert "Tags" in body
        assert "jane@example.com" in body

    # --- Downloadable error CSV endpoint ---

    def test_import_error_csv_download_not_found(self, client, admin_user):
        """Downloading error CSV for a non-existent import returns 404."""
        headers = self._admin_headers(admin_user)
        resp = client.get("/api/admin/newsletter-subscribers/import/error-csv/nonexistent-id", headers=headers)
        assert resp.status_code == 404
