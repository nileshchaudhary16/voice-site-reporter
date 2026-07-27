"""
sheets_logger.py — Google Sheets logging via gspread

Appends structured site reports as new rows.
Keeps raw transcript as audit trail in the last column.
"""

import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from dotenv import load_dotenv
from pipeline import SiteReport

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Column headers — must match the row order in log_report()
HEADERS = [
    "Timestamp",
    "Site Name",
    "Machine ID",
    "Activity",
    "Material",
    "Quantity",
    "Unit",
    "Reported By",
    "Notes",
    "Anomaly Flag",
    "Raw Transcript",
    "Source",         # "streamlit" or "whatsapp"
]


def get_sheet():
    """Authenticate and return the first sheet of SiteReports."""
    # Support both local file and Streamlit Cloud (via streamlit_secrets_adapter)
    creds_path = (
        os.getenv("GOOGLE_CREDENTIALS_PATH")  # set by streamlit_secrets_adapter on cloud
        or "credentials.json"                  # default local path
    )
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            "credentials.json not found. See SETUP_GUIDE.md for Google Cloud setup."
        )

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet_name = os.getenv("GOOGLE_SHEET_NAME", "SiteReports")

    try:
        spreadsheet = client.open(sheet_name)
    except gspread.exceptions.SpreadsheetNotFound:
        raise ValueError(
            f"Google Sheet '{sheet_name}' not found. "
            "Make sure you created it and shared it with the service account email."
        )

    return spreadsheet.sheet1


def ensure_headers(sheet):
    """Add header row if the sheet is empty."""
    existing = sheet.row_values(1)
    if not existing:
        sheet.insert_row(HEADERS, index=1)
        # Format header row bold (best-effort)
        try:
            sheet.format("A1:L1", {"textFormat": {"bold": True}})
        except Exception:
            pass  # Non-critical


def log_report(report: SiteReport, transcript: str, source: str = "streamlit") -> list:
    """
    Append a single site report as a new row in Google Sheets.

    Args:
        report: Extracted SiteReport object
        transcript: Raw transcript text (audit trail)
        source: "streamlit" or "whatsapp"

    Returns:
        The row that was appended as a list.
    """
    sheet = get_sheet()
    ensure_headers(sheet)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    anomaly = "🚨 HIGH" if report.is_anomaly else ""

    row = [
        now,
        report.site_name or "",
        report.machine_id or "",
        report.activity or "",
        report.material or "",
        str(report.quantity) if report.quantity is not None else "",
        report.unit or "",
        report.reported_by or "",
        report.notes or "",
        anomaly,
        transcript,
        source,
    ]

    sheet.append_row(row, value_input_option="USER_ENTERED")
    return row


def log_reports(reports: list[SiteReport], transcript: str, source: str = "streamlit") -> list[list]:
    """
    Append MULTIPLE site reports extracted from a single voice note.
    Each entry gets its own row but shares the same raw transcript for audit purposes,
    so you can trace every logged row back to the original recording.

    Args:
        reports: List of extracted SiteReport objects (one voice note → many entries)
        transcript: Raw transcript text — shared across all rows from this recording
        source: "streamlit" or "whatsapp"

    Returns:
        List of rows that were appended.
    """
    sheet = get_sheet()
    ensure_headers(sheet)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []

    for report in reports:
        anomaly = "🚨 HIGH" if report.is_anomaly else ""
        row = [
            now,
            report.site_name or "",
            report.machine_id or "",
            report.activity or "",
            report.material or "",
            str(report.quantity) if report.quantity is not None else "",
            report.unit or "",
            report.reported_by or "",
            report.notes or "",
            anomaly,
            transcript,
            source,
        ]
        rows.append(row)

    # Batch append is more efficient and avoids hitting Sheets API rate limits
    sheet.append_rows(rows, value_input_option="USER_ENTERED")
    return rows


def get_recent_entries(n: int = 10) -> list[list]:
    """Return the last n data rows (excluding header)."""
    try:
        sheet = get_sheet()
        all_rows = sheet.get_all_values()
        if len(all_rows) <= 1:
            return []
        # Return last n rows (skip header row 0)
        data_rows = all_rows[1:]
        return data_rows[-n:]
    except Exception:
        return []


def get_all_as_dicts() -> list[dict]:
    """Return all rows as list of dicts (header keys)."""
    try:
        sheet = get_sheet()
        return sheet.get_all_records()
    except Exception:
        return []
