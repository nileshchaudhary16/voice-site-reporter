"""
test_pipeline.py — Verify each component works before running the full app

Run with: python test_pipeline.py
Tests each component in isolation so you can debug step by step.
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

results = []


def section(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")


def check(label, ok, detail=""):
    status = PASS if ok else FAIL
    msg = f"  {status} {label}"
    if detail:
        msg += f"\n     → {detail}"
    print(msg)
    results.append((label, ok))


# ── 1. Environment variables ─────────────────────────────────────
section("1. Environment Variables")

gemini_key = os.getenv("GEMINI_API_KEY")
groq_key  = os.getenv("GROQ_API_KEY")
sheet_name = os.getenv("GOOGLE_SHEET_NAME")

check("GEMINI_API_KEY set", bool(gemini_key),
      f"Key starts with: {gemini_key[:8]}..." if gemini_key else "Not found in .env")
check("GROQ_API_KEY set", bool(groq_key),
      f"Key starts with: {groq_key[:8]}..." if groq_key else "Not found in .env — get free key at https://console.groq.com")
check("GOOGLE_SHEET_NAME set", bool(sheet_name),
      f"Sheet name: '{sheet_name}'" if sheet_name else "Not found in .env")
check("credentials.json exists", os.path.exists("credentials.json"),
      "Found" if os.path.exists("credentials.json") else "Missing — see SETUP_GUIDE.md Step 4")


# ── 2. Python imports ────────────────────────────────────────────
section("2. Python Package Imports")

packages = [
    ("streamlit",               "streamlit"),
    ("google.generativeai",     "google-generativeai"),
    ("gspread",                 "gspread"),
    ("pydantic",                "pydantic"),
    ("flask",                   "flask"),
    ("requests",                "requests"),
    ("audio_recorder_streamlit","audio-recorder-streamlit"),
    ("twilio",                  "twilio"),
    ("soundfile",               "soundfile"),
    ("numpy",                   "numpy"),
]

for module, pip_name in packages:
    try:
        __import__(module)
        check(f"import {module}", True)
    except ImportError:
        check(f"import {module}", False, f"Run: pip install {pip_name}")


# ── 3. Gemini API ────────────────────────────────────────────────
section("3. Gemini API Connection")

if gemini_key:
    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_key)
        from pipeline import _get_working_model_name
        detected_model = _get_working_model_name()
        model = genai.GenerativeModel(detected_model)
        response = model.generate_content(
            'Reply with exactly this JSON and nothing else: {"test": "ok"}'
        )
        text = response.text.strip()
        ok = "ok" in text.lower()
        check("Gemini API call", ok, f"Model: {detected_model} | Response: {text[:80]}")
    except Exception as e:
        check("Gemini API call", False, str(e))
else:
    print(f"  {WARN} Skipped — GEMINI_API_KEY not set")


# ── 4. Gemini extraction test ────────────────────────────────────
section("4. Structured Extraction (Gemini)")

if gemini_key:
    try:
        from pipeline import extract_structured_data

        # Single-entry test
        test_transcript = "Machine 2 maa diesel bharyo 40 litre, Kathwada site par, Ramesh e report karyun"
        reports, err = extract_structured_data(test_transcript)
        if err:
            check("Single-entry extraction", False, err)
        elif len(reports) != 1:
            check("Single-entry extraction", False, f"Expected 1 entry, got {len(reports)}")
        else:
            r = reports[0]
            check("Single-entry extraction", True,
                  f"Site={r.site_name}, Machine={r.machine_id}, Material={r.material}, Qty={r.quantity} {r.unit}")

        # Multi-entry test — supervisor rattling off two updates in one breath
        multi_transcript = (
            "Machine 2 maa diesel bharyo 40 litre Kathwada site par, "
            "ane Machine 5 nu kaam pura thayu Sanand site par"
        )
        multi_reports, err2 = extract_structured_data(multi_transcript)
        if err2:
            check("Multi-entry extraction", False, err2)
        else:
            check("Multi-entry extraction", len(multi_reports) >= 2,
                  f"Found {len(multi_reports)} entries — "
                  f"{[r.site_name for r in multi_reports]}")
    except Exception as e:
        check("Extraction from test transcript", False, str(e))
else:
    print(f"  {WARN} Skipped — GEMINI_API_KEY not set")


# ── 5. Groq API (Speech-to-Text) ────────────────────────────────
section("5. Groq API (Speech-to-Text via Whisper)")

if groq_key:
    try:
        import requests as req
        # Probe the Groq models endpoint to verify token validity
        r = req.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {groq_key}"},
            timeout=10,
        )
        if r.status_code == 200:
            models = [m["id"] for m in r.json().get("data", []) if "whisper" in m["id"]]
            check("Groq API token valid", True,
                  f"Whisper models available: {', '.join(models) or 'whisper-large-v3-turbo'}")
        elif r.status_code == 401:
            check("Groq API token valid", False, "Token is invalid or expired")
        else:
            check("Groq API reachable", False, f"Status {r.status_code}: {r.text[:100]}")
    except Exception as e:
        check("Groq API reachable", False, str(e))
else:
    print(f"  {WARN} Skipped — GROQ_API_KEY not set")
    print(f"       Get a free key at: https://console.groq.com → API Keys")


# ── 6. Google Sheets connection ──────────────────────────────────
section("6. Google Sheets Connection")

if os.path.exists("credentials.json"):
    try:
        from sheets_logger import get_sheet, ensure_headers
        sheet = get_sheet()
        check("Google Sheets auth", True, f"Connected to sheet: '{sheet.title}'")

        ensure_headers(sheet)
        check("Headers initialized", True, "Header row ready")

        row_count = len(sheet.get_all_values())
        check("Sheet readable", True, f"{row_count} rows (including header)")
    except FileNotFoundError as e:
        check("Google Sheets auth", False, str(e))
    except ValueError as e:
        check("Google Sheets auth", False, str(e))
    except Exception as e:
        check("Google Sheets auth", False, f"{type(e).__name__}: {str(e)}")
else:
    print(f"  {WARN} Skipped — credentials.json not found")


# ── 7. Anomaly detection logic ───────────────────────────────────
section("7. Anomaly Detection Logic")

try:
    from pipeline import SiteReport

    normal = SiteReport(material="diesel", quantity=40, unit="litre")
    check("Normal diesel (40L) — not anomaly", not normal.is_anomaly,
          f"is_anomaly={normal.is_anomaly}")

    high = SiteReport(material="diesel", quantity=150, unit="litre")
    check("High diesel (150L) — flagged as anomaly", high.is_anomaly,
          f"is_anomaly={high.is_anomaly}")

    cement = SiteReport(material="cement", quantity=200, unit="bags")
    check("Cement (200 bags) — not anomaly", not cement.is_anomaly,
          "Anomaly only applies to diesel")
except Exception as e:
    check("Anomaly detection", False, str(e))


# ── Summary ──────────────────────────────────────────────────────
section("Summary")

passed = sum(1 for _, ok in results if ok)
total  = len(results)
failed = [(label, ok) for label, ok in results if not ok]

print(f"\n  {passed}/{total} checks passed\n")

if failed:
    print("  Items to fix:")
    for label, _ in failed:
        print(f"    {FAIL} {label}")
    print("\n  See SETUP_GUIDE.md for instructions on each item.")
else:
    print(f"  {PASS} All checks passed! Run the app with:")
    print("     streamlit run app.py")
    print("     python whatsapp_webhook.py  (in another terminal for WhatsApp)")

print()
