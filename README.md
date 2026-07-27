# Voice-Based Site Reporting System 🏗️
**Bol ke report karo — Gujarati ya Hindi mein**

A Bharat-first, voice-driven site reporting tool for construction and earthmoving businesses.
Workers speak in Gujarati or Hindi → AI transcribes + extracts structured data → logs to Google Sheets.

---

## Project Structure
```
voice_site_reporter/
├── app.py                  # Streamlit UI (main app)
├── pipeline.py             # ASR + Gemini extraction core
├── sheets_logger.py        # Google Sheets logging
├── whatsapp_webhook.py     # Twilio WhatsApp webhook (Flask)
├── .env                    # API keys (never commit this)
├── credentials.json        # Google service account (never commit this)
├── requirements.txt
└── SETUP_GUIDE.md          # Step-by-step API setup instructions
```

---

## Quick Start (after setup)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy and fill in your keys
cp .env.example .env

# 3. Run the Streamlit app
streamlit run app.py

# 4. (Optional) Run WhatsApp webhook in a separate terminal
python whatsapp_webhook.py
```

---

## Features
- 🎙️ Voice recording in browser (Gujarati + Hindi)
- 🤖 Whisper ASR via Hugging Face Inference API
- 🧠 Gemini 2.0 Flash structured data extraction
- 📊 Auto-logs to Google Sheets with raw transcript audit trail
- 📱 WhatsApp voice note support via Twilio
- ✅ Manual confirmation before logging
- 📋 Live view of last 10 entries
- 🚨 Anomaly flag if diesel > 100 litres
