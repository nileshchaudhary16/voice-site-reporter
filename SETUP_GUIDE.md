# Setup Guide — Voice Site Reporter

Follow these steps in order. The whole setup takes about 45–60 minutes.

---

## Step 1 — Install Python dependencies

Open your terminal in the project folder and run:

```bash
pip install -r requirements.txt
```

If you're on Windows and get errors with `soundfile`, also run:
```bash
pip install soundfile --extra-index-url https://pypi.anaconda.org/cleudinn/simple
```

---

## Step 2 — Get a Gemini API Key (Free)

1. Go to **https://aistudio.google.com/app/apikey**
2. Sign in with your Google account
3. Click **"Create API Key"**
4. Copy the key — it looks like `AIzaSy...`

---

## Step 3 — Get a Hugging Face Token (Free)

The app uses Hugging Face Inference API for Gujarati/Hindi speech recognition.
No GPU or local model download needed — it runs in the cloud.

1. Go to **https://huggingface.co** → Sign up (free)
2. Go to **Settings → Access Tokens**
3. Click **"New token"** → Name it "site-reporter" → Role: **Read**
4. Copy the token — it looks like `hf_...`

> **Note:** The Gujarati Whisper model (`vasista22/whisper-gujarati-small`) may take
> 20-30 seconds to load on first use (cold start). After that it's fast.

---

## Step 4 — Set Up Google Sheets

### 4a. Create a Google Cloud project

1. Go to **https://console.cloud.google.com**
2. Click the project dropdown → **"New Project"**
3. Name it `site-reporter` → click **Create**

### 4b. Enable APIs

In your new project:
1. Go to **APIs & Services → Library**
2. Search **"Google Sheets API"** → Enable it
3. Search **"Google Drive API"** → Enable it

### 4c. Create a service account

1. Go to **APIs & Services → Credentials**
2. Click **"Create Credentials" → "Service Account"**
3. Name: `site-reporter-bot` → click **Create and Continue**
4. Role: select **"Editor"** → click **Continue → Done**

### 4d. Download credentials

1. Click on your new service account (in the credentials list)
2. Go to the **"Keys"** tab
3. Click **"Add Key" → "Create new key" → JSON**
4. A file downloads — rename it to **`credentials.json`**
5. Move it into your `voice_site_reporter/` folder

### 4e. Create the Google Sheet

1. Go to **https://sheets.google.com** → create a new blank sheet
2. Name it exactly: **`SiteReports`**
3. Open `credentials.json` and find the `client_email` field (looks like `site-reporter-bot@your-project.iam.gserviceaccount.com`)
4. In Google Sheets: **Share → Add that email → Editor access**

---

## Step 5 — Configure .env file

Copy the example file:
```bash
cp .env.example .env
```

Open `.env` and fill in your keys:

```env
GEMINI_API_KEY=AIzaSy...          # from Step 2
HF_API_TOKEN=hf_...               # from Step 3
GOOGLE_SHEET_NAME=SiteReports     # must match exactly
TWILIO_ACCOUNT_SID=               # from Step 6 (optional for now)
TWILIO_AUTH_TOKEN=                # from Step 6 (optional for now)
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
MANAGER_WHATSAPP=+91XXXXXXXXXX    # your number for anomaly alerts
```

---

## Step 6 — Run the Streamlit App

```bash
streamlit run app.py
```

Your browser will open at **http://localhost:8501**

Test it:
- Select "Gujarati" 
- Click the microphone, say: *"Machine 2, diesel bharyo 40 litre, Kathwada site"*
- Watch it transcribe, extract, and log

---

## Step 7 — WhatsApp Integration via Meta Cloud API (Free tier: 1,000 conversations/month)

This uses Meta's own official WhatsApp Business API — no Twilio, no markup on messages.

### 7a. Create a Meta Developer account

1. Go to **https://developers.facebook.com** → click **"Get Started"**
2. Log in with a Facebook account (create one if needed — this can be personal, doesn't need to be a page)
3. Complete the developer registration (verify email/phone if asked)

### 7b. Create an App

1. Go to **https://developers.facebook.com/apps** → click **"Create App"**
2. Choose **"Other"** as the use case → click **Next**
3. Choose **"Business"** as the app type → click **Next**
4. Name it `SiteReporter` → select or create a Business Portfolio → click **Create App**

### 7c. Add the WhatsApp Product

1. On your new app's dashboard, find **"WhatsApp"** in the product list → click **Set up**
2. This takes you to **WhatsApp → API Setup**
3. Meta automatically gives you a **free test phone number** here — no cost, no verification needed for testing

### 7d. Get your credentials

Still on the **API Setup** page, you'll see:

- **Temporary access token** — valid for 24 hours (good for testing). Copy it → paste into `.env` as `META_ACCESS_TOKEN`
- **Phone number ID** — shown right there on the page. Copy it → paste into `.env` as `META_PHONE_NUMBER_ID`

> ⚠️ The temporary token expires every 24 hours during testing. For a token that doesn't expire,
> generate a **System User access token** later under **Business Settings → System Users**
> (needed only when you move past testing).

### 7e. Add a test recipient number

Meta's test number can only message phone numbers you've explicitly added:

1. Still on **API Setup**, find **"To"** field → click **"Manage phone number list"**
2. Add your own WhatsApp number (and any worker's number you're testing with)
3. Verify via the OTP sent to that number

### 7f. Set your verify token

In your `.env`, set any string you like as your webhook secret:
```env
META_VERIFY_TOKEN=site-reporter-verify
```
You'll enter this exact same string into Meta's console in step 7h.

### 7g. Install and run ngrok (exposes your local server)

```bash
# Download from https://ngrok.com/download
ngrok http 5000
```
Copy the HTTPS URL it prints (e.g. `https://abc123.ngrok-free.app`)

### 7h. Configure the webhook in Meta

1. In your app dashboard → **WhatsApp → Configuration**
2. Click **"Edit"** next to Webhook
3. **Callback URL:** `https://abc123.ngrok-free.app/whatsapp`
4. **Verify token:** paste the exact same value you set as `META_VERIFY_TOKEN`
5. Click **Verify and Save** (this triggers a GET request your webhook must respond to correctly — it will, automatically)
6. Under **"Webhook fields"**, click **Manage** → subscribe to **`messages`**

### 7i. Run the webhook server

In a separate terminal (keep `streamlit run app.py` running in the first one):
```bash
python whatsapp_webhook.py
```

Now send a voice note to your test WhatsApp number from a number you added in step 7e!


Now send a voice note to your test WhatsApp number from a number you added in step 7e!

---

## Step 8 — Deploy to Streamlit Cloud (optional)

To share with workers via a URL:

1. Push your project to GitHub (exclude `.env` and `credentials.json` — add to `.gitignore`)
2. Go to **https://share.streamlit.io** → Connect your GitHub repo
3. Add secrets in Streamlit Cloud settings (replaces `.env`):
   ```toml
   GEMINI_API_KEY = "AIzaSy..."
   HF_API_TOKEN = "hf_..."
   GOOGLE_SHEET_NAME = "SiteReports"
   ```
4. For `credentials.json`, paste the entire JSON content as a secret:
   ```toml
   GOOGLE_CREDENTIALS = '''{"type": "service_account", ...}'''
   ```
   Then update `sheets_logger.py` to load from `st.secrets` instead of file.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Model is loading" on first transcription | Wait 30 seconds, try again — HF cold start |
| "SpreadsheetNotFound" | Check sheet name is exactly `SiteReports` and shared with service account |
| Audio recorder not working | Try Chrome browser; mobile Safari has mic permission issues |
| WhatsApp webhook not receiving | Check ngrok is running and the URL is verified in Meta's Webhook Configuration |
| Meta access token expired | Temporary tokens expire every 24h — get a fresh one from API Setup, or create a System User token for long-term use |
| Empty transcript | Speak closer to mic; try a quieter environment |
| Gemini returns wrong JSON | Usually fixes itself; report the transcript and we can tune the prompt |

---

## .gitignore (important!)

Add this to your `.gitignore` to never accidentally commit secrets:

```
.env
credentials.json
*.wav
__pycache__/
.streamlit/secrets.toml
```
