"""
streamlit_secrets_adapter.py

When deploying to Streamlit Cloud, credentials.json cannot be uploaded as a file.
Instead, paste the entire JSON content as a Streamlit secret called GOOGLE_CREDENTIALS.

This helper writes the credentials to a temp file at startup so gspread can read it.

HOW TO USE:
    Add this one line at the very top of app.py (before any other imports):
        import streamlit_secrets_adapter  # noqa: F401

STREAMLIT CLOUD SECRETS FORMAT (paste in Settings → Secrets):
    GEMINI_API_KEY = "AIzaSy..."
    HF_API_TOKEN = "hf_..."
    GOOGLE_SHEET_NAME = "SiteReports"

    [GOOGLE_CREDENTIALS]
    type = "service_account"
    project_id = "your-project-id"
    private_key_id = "..."
    private_key = "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n"
    client_email = "site-reporter-bot@your-project.iam.gserviceaccount.com"
    client_id = "..."
    auth_uri = "https://accounts.google.com/o/oauth2/auth"
    token_uri = "https://oauth2.googleapis.com/token"
    auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
    client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/..."
    universe_domain = "googleapis.com"
"""

import os
import json
import tempfile

# Only runs on Streamlit Cloud (where st.secrets exists and credentials.json doesn't)
try:
    import streamlit as st

    if hasattr(st, "secrets") and "GOOGLE_CREDENTIALS" in st.secrets:
        # Write credentials from secrets to a temp file
        creds_dict = dict(st.secrets["GOOGLE_CREDENTIALS"])
        creds_path = os.path.join(tempfile.gettempdir(), "credentials.json")

        with open(creds_path, "w") as f:
            json.dump(creds_dict, f)

        # Point the env var to it so sheets_logger picks it up
        os.environ["GOOGLE_CREDENTIALS_PATH"] = creds_path

        # Also set other secrets as env vars for the rest of the app
        for key in ["GEMINI_API_KEY", "HF_API_TOKEN", "GOOGLE_SHEET_NAME"]:
            if key in st.secrets and not os.getenv(key):
                os.environ[key] = st.secrets[key]

except ImportError:
    pass  # Not running in Streamlit context, skip silently
