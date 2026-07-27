"""
whatsapp_webhook.py — WhatsApp integration via Meta's official Cloud API (FREE tier)

Workers send a voice note → this webhook transcribes + extracts it → sends
back a summary asking for confirmation → only logs to Sheets once the
worker replies YES. This catches misspoken entries or bad transcriptions
before anything gets written to the sheet.

Run with:      python whatsapp_webhook.py
Expose it via: ngrok http 5000
Then set the webhook URL in Meta Developer Console (see SETUP_GUIDE.md § WhatsApp).
"""

import os
import time
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from pipeline import run_pipeline, SiteReport
from sheets_logger import log_reports

load_dotenv(override=True)

app = Flask(__name__)

META_ACCESS_TOKEN    = os.getenv("META_ACCESS_TOKEN")
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID")
META_VERIFY_TOKEN    = os.getenv("META_VERIFY_TOKEN", "site-reporter-verify")
META_API_VERSION     = "v20.0"
GRAPH_BASE = f"https://graph.facebook.com/{META_API_VERSION}"

MANAGER_WHATSAPP = os.getenv("MANAGER_WHATSAPP")

# ── Pending confirmations ────────────────────────────────────────
# Keyed by sender's phone number. Holds the transcript + extracted reports
# for a voice note that's waiting on a YES/NO reply before it gets logged.
# In-memory only — fine for a small pilot; resets if the server restarts.
PENDING_CONFIRMATIONS: dict[str, dict] = {}

CONFIRM_WORDS = {"yes", "y", "1", "ok", "okay", "confirm", "haa", "ha", "sahi"}
DISCARD_WORDS = {"no", "n", "2", "cancel", "discard", "na", "nahi"}


@app.route("/whatsapp", methods=["GET"])
def verify_webhook():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        print("✅ Webhook verified by Meta")
        return challenge, 200
    print("❌ Webhook verification failed — token mismatch")
    return "Verification failed", 403


@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    data = request.get_json()
    print(f"\n📱 Incoming webhook payload received")

    try:
        entry   = data["entry"][0]
        changes = entry["changes"][0]
        value   = changes["value"]

        if "messages" not in value:
            return jsonify(status="ok"), 200

        message  = value["messages"][0]
        sender   = message["from"]
        msg_type = message["type"]

        print(f"   From: {sender} | Type: {msg_type}")

        if msg_type == "audio":
            handle_voice_note(message, sender)
        elif msg_type == "text":
            handle_text_message(message, sender)
        else:
            send_whatsapp_message(sender,
                "⚠️ Please send a *voice note* describing your site activity.")

    except (KeyError, IndexError) as e:
        print(f"   ⚠️ Unexpected payload structure: {e}")

    return jsonify(status="ok"), 200


def handle_text_message(message: dict, sender: str):
    """
    Text messages are either:
      - a YES/NO reply to a pending confirmation, or
      - anything else → show help text
    """
    body = message.get("text", {}).get("body", "").strip().lower()

    pending = PENDING_CONFIRMATIONS.get(sender)

    if pending:
        if body in CONFIRM_WORDS:
            _finalize_pending(sender)
            return
        elif body in DISCARD_WORDS:
            del PENDING_CONFIRMATIONS[sender]
            send_whatsapp_message(sender, "🗑️ Discarded. Send a new voice note whenever you're ready.")
            return
        else:
            send_whatsapp_message(sender,
                "🤔 I have a report waiting for your confirmation.\n\n"
                "Reply *YES* to log it, or *NO* to discard it.")
            return

    help_text = (
        "🏗️ *Site Voice Reporter*\n\n"
        "Send a *voice note* describing your site activity.\n\n"
        "Example (Gujarati):\n"
        "_Machine 2, diesel bharyo 40 litre, Kathwada site par_\n\n"
        "Example (Hindi):\n"
        "_Machine number 3 mein 60 litre diesel bhara, Sanand site_\n\n"
        "I'll show you what I understood before logging it — "
        "just reply YES to confirm or NO to discard."
    )
    send_whatsapp_message(sender, help_text)


def handle_voice_note(message: dict, sender: str):
    """
    Download → transcribe → extract → send a SUMMARY and WAIT for confirmation.
    Nothing gets logged to Sheets until the worker replies YES.
    """
    audio_id = message["audio"]["id"]

    send_whatsapp_message(sender, "🎙️ Got your voice note! Processing...")

    audio_bytes = download_meta_media(audio_id)
    if not audio_bytes:
        send_whatsapp_message(sender, "❌ Could not download your audio. Please try again.")
        return

    lang_code = "gu"  # default — change to "hi" if your workers mostly speak Hindi
    result = run_pipeline(audio_bytes, lang_code)
    transcript = result["transcript"]
    reports: list[SiteReport] = result["reports"]

    print(f"   Transcript: {transcript}")
    print(f"   Entries found: {len(reports)}")

    if not transcript:
        send_whatsapp_message(sender, f"❌ {result['error'] or 'Could not transcribe audio.'}")
        return

    if not reports:
        send_whatsapp_message(sender, f"⚠️ Could not extract any entries from:\n_{transcript}_")
        return

    # Store as pending — waiting for the worker's YES/NO reply
    PENDING_CONFIRMATIONS[sender] = {
        "transcript": transcript,
        "reports": [r.model_dump() for r in reports],
        "timestamp": time.time(),
    }

    summary = build_review_message(reports, transcript)
    send_whatsapp_message(sender, summary)


def _finalize_pending(sender: str):
    """Called when a worker replies YES — actually logs to Sheets now."""
    pending = PENDING_CONFIRMATIONS.pop(sender, None)
    if not pending:
        send_whatsapp_message(sender, "⚠️ Nothing to confirm right now. Send a voice note first.")
        return

    reports = [SiteReport(**r) for r in pending["reports"]]
    transcript = pending["transcript"]

    try:
        log_reports(reports, transcript, source="whatsapp")
        n = len(reports)
        send_whatsapp_message(sender, f"✅ Logged {n} {'entries' if n != 1 else 'entry'} to the sheet!")

        for report in reports:
            if report.is_anomaly and MANAGER_WHATSAPP:
                send_anomaly_alert(report, transcript, sender)

    except Exception as e:
        print(f"   ❌ Sheets logging error: {e}")
        send_whatsapp_message(sender, f"⚠️ Confirmed but logging failed: {e}")


def build_review_message(reports: list[SiteReport], transcript: str) -> str:
    """Summary shown BEFORE logging — asks for YES/NO confirmation."""
    n = len(reports)
    lines = [f"📋 *Here's what I understood* ({n} {'entries' if n != 1 else 'entry'}):\n"]

    for i, report in enumerate(reports, start=1):
        entry_lines = []
        if n > 1:
            entry_lines.append(f"*Entry {i}:*")
        if report.site_name:   entry_lines.append(f"📍 Site: {report.site_name}")
        if report.machine_id:  entry_lines.append(f"🚜 Machine: {report.machine_id}")
        if report.activity:    entry_lines.append(f"⚡ Activity: {report.activity}")
        if report.material and report.quantity:
            entry_lines.append(f"📦 {report.material.capitalize()}: {report.quantity} {report.unit or ''}")
        elif report.material:
            entry_lines.append(f"📦 Material: {report.material}")
        if report.reported_by: entry_lines.append(f"👤 By: {report.reported_by}")
        if report.notes:       entry_lines.append(f"📝 Notes: {report.notes}")
        if report.is_anomaly:
            entry_lines.append("🚨 *HIGH QUANTITY — please double check*")
        lines.append("\n".join(entry_lines))

    lines.append(f"\n_Heard: \"{transcript}\"_")
    lines.append("\n✅ Reply *YES* to log this, or *NO* to discard and re-record.")
    return "\n\n".join(lines)


def download_meta_media(media_id: str) -> bytes | None:
    try:
        r1 = requests.get(
            f"{GRAPH_BASE}/{media_id}",
            headers={"Authorization": f"Bearer {META_ACCESS_TOKEN}"},
            timeout=15,
        )
        if r1.status_code != 200:
            print(f"   ❌ Media lookup failed: {r1.status_code} {r1.text[:150]}")
            return None
        media_url = r1.json().get("url")

        r2 = requests.get(
            media_url,
            headers={"Authorization": f"Bearer {META_ACCESS_TOKEN}"},
            timeout=30,
        )
        if r2.status_code != 200:
            print(f"   ❌ Media download failed: {r2.status_code}")
            return None

        return r2.content

    except Exception as e:
        print(f"   ❌ Media download error: {e}")
        return None


def send_whatsapp_message(to: str, body: str):
    if not META_ACCESS_TOKEN or not META_PHONE_NUMBER_ID:
        print("   ⚠️ Meta credentials not set — cannot send reply")
        return

    try:
        resp = requests.post(
            f"{GRAPH_BASE}/{META_PHONE_NUMBER_ID}/messages",
            headers={
                "Authorization": f"Bearer {META_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": body},
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"   ⚠️ Send failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"   ⚠️ Send error: {e}")


def send_anomaly_alert(report: SiteReport, transcript: str, reported_by_number: str):
    if not MANAGER_WHATSAPP:
        return
    alert = (
        f"🚨 *ANOMALY ALERT — High Diesel Quantity*\n\n"
        f"📍 Site: {report.site_name or 'Unknown'}\n"
        f"🚜 Machine: {report.machine_id or 'Unknown'}\n"
        f"⛽ Quantity: {report.quantity} {report.unit or 'litres'}\n"
        f"📱 From: {reported_by_number}\n\n"
        f"_{transcript}_\n\nPlease verify in Google Sheets."
    )
    send_whatsapp_message(MANAGER_WHATSAPP, alert)


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "service": "Site Reporter — Meta WhatsApp Webhook",
            "pending_confirmations": len(PENDING_CONFIRMATIONS)}, 200


@app.route("/", methods=["GET"])
def index():
    return """
    <h2>🏗️ Site Voice Reporter — WhatsApp Webhook (Meta Cloud API)</h2>
    <p>Status: <strong style="color:green">Running</strong></p>
    <p>Webhook URL: <code>/whatsapp</code> (GET for verification, POST for messages)</p>
    <p>Health check: <a href="/health">/health</a></p>
    <p>Confirmation flow: voice note → summary → worker replies YES/NO → logs on YES</p>
    """


if __name__ == "__main__":
    print("\n🏗️ Site Voice Reporter — Meta WhatsApp Webhook")
    print("=" * 55)
    print("Local URL: http://localhost:5000/whatsapp")
    print("Confirmation flow enabled — nothing logs until worker replies YES")
    print("\nExpose with:  ngrok http 5000")
    print("Then set the ngrok HTTPS URL as your webhook in")
    print("Meta Developer Console → WhatsApp → Configuration")
    print("=" * 55)

    if not META_ACCESS_TOKEN:
        print("⚠️  META_ACCESS_TOKEN not set — see SETUP_GUIDE.md")
    if not META_PHONE_NUMBER_ID:
        print("⚠️  META_PHONE_NUMBER_ID not set — see SETUP_GUIDE.md")
    if not os.getenv("GEMINI_API_KEY"):
        print("⚠️  GEMINI_API_KEY not set")
    if not os.getenv("GROQ_API_KEY"):
        print("⚠️  GROQ_API_KEY not set")

    app.run(debug=True, port=5000)
