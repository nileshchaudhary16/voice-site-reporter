"""
pipeline.py — Core ASR + Gemini extraction pipeline

ASR:        Groq Whisper API — whisper-large-v3 (full model, NOT turbo).
            The turbo variant trades accuracy for speed, and that trade-off
            hurts lower-resource languages like Gujarati the most. Full
            large-v3 is slower but noticeably more accurate for Indian
            languages — worth it since correctness matters more than speed here.
Extraction: Gemini — auto-detects the best available model on your API key
            (prioritizing gemini-2.5-flash-lite), returns a LIST of entries
            since one voice note may describe multiple machines/sites/activities.
"""

import os
import json
import time
import requests
import google.generativeai as genai
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_ASR_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Full model, not turbo — meaningfully better accuracy for Gujarati/Hindi.
GROQ_ASR_MODEL = "whisper-large-v3"

# Prompt hints bias Whisper's decoding toward domain vocabulary — this helps
# it choose "Kathwada" over a similar-sounding wrong word, etc. Add your own
# common site names / machine names here to further improve accuracy.
LANGUAGE_PROMPTS = {
    "gu": (
        "Construction site voice report in Gujarati. "
        "Vocabulary: diesel bharyo, machine, litre, JCB, excavator, dumper, "
        "site, Kathwada, Sanand, Bavla, Himatnagar, bags, cement, trips."
    ),
    "hi": (
        "Construction site voice report in Hindi. "
        "Vocabulary: diesel bhara, machine, litre, JCB, excavator, dumper, "
        "site, Kathwada, Sanand, Bavla, Himatnagar, bags, cement, trips."
    ),
}


# ── Pydantic schema ─────────────────────────────────────────────
class SiteReport(BaseModel):
    site_name: Optional[str] = None
    machine_id: Optional[str] = None
    activity: Optional[str] = None
    material: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    reported_by: Optional[str] = None
    notes: Optional[str] = None

    @property
    def is_anomaly(self) -> bool:
        if self.material and "diesel" in self.material.lower():
            if self.quantity and self.quantity > 100:
                return True
        return False

    def to_display_dict(self) -> dict:
        return {
            "Site": self.site_name or "—",
            "Machine": self.machine_id or "—",
            "Activity": self.activity or "—",
            "Material": self.material or "—",
            "Quantity": f"{self.quantity} {self.unit}" if self.quantity else "—",
            "Reported by": self.reported_by or "—",
            "Notes": self.notes or "—",
        }


# ── Step 1: Transcribe audio via Groq Whisper (full model) ─────
def transcribe_audio(audio_bytes: bytes, language: str = "gu") -> tuple[str, bool]:
    if not GROQ_API_KEY:
        return "❌ GROQ_API_KEY not set in .env file. Get a free key at https://console.groq.com", False

    prompt = LANGUAGE_PROMPTS.get(language, LANGUAGE_PROMPTS["gu"])
    lang_code = "gu" if language == "gu" else "hi"

    try:
        response = requests.post(
            GROQ_ASR_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": ("audio.wav", audio_bytes, "audio/wav")},
            data={
                "model": GROQ_ASR_MODEL,
                "language": lang_code,
                "prompt": prompt,
                "response_format": "json",
                "temperature": 0.0,
            },
            timeout=60,  # full model is slower than turbo — allow more time
        )

        if response.status_code == 401:
            return "❌ Invalid GROQ_API_KEY.", False
        if response.status_code == 429:
            return "⏳ Groq rate limit hit. Wait a moment and try again.", False
        if response.status_code != 200:
            return f"❌ Groq API error {response.status_code}: {response.text[:200]}", False

        data = response.json()
        text = data.get("text", "").strip()

        if not text:
            return "⚠️ No speech detected. Please speak clearly and try again.", False

        return text, True

    except requests.exceptions.ConnectionError:
        return "❌ Cannot reach Groq API. Check your internet connection.", False
    except requests.exceptions.Timeout:
        return "❌ Request timed out. Please try again.", False
    except Exception as e:
        return f"❌ Transcription error: {str(e)}", False


# ── Gemini model auto-detection (self-heals if a model gets deprecated) ─
_CACHED_MODEL_NAME = None

_MODEL_PREFERENCE = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
    "gemini-2.0-flash-001",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
]


def _get_working_model_name() -> str:
    """Ask the API key what models it can actually use, prefer flash-lite."""
    global _CACHED_MODEL_NAME
    if _CACHED_MODEL_NAME:
        return _CACHED_MODEL_NAME

    try:
        available = []
        for m in genai.list_models():
            if "generateContent" in m.supported_generation_methods:
                name = m.name.split("/")[-1]  # strip "models/" prefix
                available.append(name)

        for preferred in _MODEL_PREFERENCE:
            if preferred in available:
                _CACHED_MODEL_NAME = preferred
                print(f"✅ Using Gemini model: {preferred}")
                return _CACHED_MODEL_NAME

        if available:
            _CACHED_MODEL_NAME = available[0]
        else:
            _CACHED_MODEL_NAME = "gemini-2.5-flash-lite"  # last-resort guess

        print(f"⚠️ No preferred model found — falling back to: {_CACHED_MODEL_NAME}")
        return _CACHED_MODEL_NAME

    except Exception as e:
        print(f"⚠️ Could not list Gemini models ({e}) — defaulting to gemini-2.5-flash-lite")
        _CACHED_MODEL_NAME = "gemini-2.5-flash-lite"
        return _CACHED_MODEL_NAME


# ── Step 2: Extract MULTIPLE structured entries via Gemini ─────
EXTRACTION_PROMPT = """You are a construction site data extraction assistant for an Indian earthmoving/construction company.

A supervisor often records ONE voice note that describes SEVERAL separate updates back to back —
different machines, different sites, different activities — because they're busy on-site and don't
have time to record one note per update. Your job is to split the transcript into ALL the distinct
entries it contains.

The transcript may be in Gujarati, Hindi, English, or a mix.

Common terms:
- diesel bharyo / diesel bharo = diesel filled
- machine = excavator / JCB / dumper / truck
- litre / liter = unit for diesel
- bags = cement bags
- trips = truck trips
- ane / aur / and = connector between separate updates — often signals a NEW entry
- site names = location names like "Kathwada", "Sanand", "Bavla"

Transcript: "{transcript}"

Identify EVERY distinct update in this transcript. A new update usually means a new machine,
a new site, a new material, or a new activity being mentioned. If the whole transcript only
describes ONE update, return an array with just one object.

Return ONLY a valid JSON array (even for a single entry) where each object has exactly these fields:
[
  {{
    "site_name": "name of construction site, or null",
    "machine_id": "machine/vehicle number or name, or null",
    "activity": "what was done e.g. 'diesel filling', 'material delivery', 'work completed', or null",
    "material": "material involved: diesel, cement, sand, steel, gravel, water, or null",
    "quantity": numeric value only, or null,
    "unit": "litre, kg, bags, trips, hours, or null",
    "reported_by": "person's name if mentioned, or null",
    "notes": "any other important detail, or null"
  }}
]

Return ONLY the JSON array. No explanation, no markdown, no backticks."""


def extract_structured_data(transcript: str, retries: int = 3) -> tuple[list[SiteReport], str]:
    """
    Extract ALL structured entries from a transcript using Gemini.
    Always returns a LIST — one item for a simple report, multiple for a
    supervisor rattling off several updates in one voice note.
    """
    if not os.getenv("GEMINI_API_KEY"):
        return [], "❌ GEMINI_API_KEY not set in .env file."

    prompt = EXTRACTION_PROMPT.format(transcript=transcript)

    for attempt in range(retries):
        try:
            model_name = _get_working_model_name()
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)

            raw_text = response.text.strip()

            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()

            data = json.loads(raw_text)

            if isinstance(data, dict):
                data = [data]

            reports = [SiteReport(**item) for item in data]

            if not reports:
                return [], "⚠️ No entries could be extracted from the transcript."

            return reports, ""

        except Exception as e:
            err_str = str(e)

            if "404" in err_str or "not found" in err_str.lower():
                # Model got deprecated mid-session — clear cache and retry once
                global _CACHED_MODEL_NAME
                print(f"⚠️ Model {_CACHED_MODEL_NAME} no longer available — re-detecting...")
                _CACHED_MODEL_NAME = None
                if attempt < retries - 1:
                    continue

            if "429" in err_str or "quota" in err_str.lower():
                if attempt < retries - 1:
                    wait = 15 * (attempt + 1)
                    print(f"⏳ Gemini rate limit, waiting {wait}s (attempt {attempt+1}/{retries})...")
                    time.sleep(wait)
                    continue
                else:
                    return [], (
                        "❌ Gemini quota exceeded. Your free tier limit is reached for today.\n"
                        "Wait until midnight, or add billing to your Google AI project."
                    )

            if isinstance(e, json.JSONDecodeError):
                return [], f"❌ JSON parse error from Gemini: {str(e)}"

            return [], f"❌ Gemini extraction error: {err_str}"

    return [], "❌ All retry attempts failed."


# ── Full pipeline (transcribe + extract multiple entries) ──────
def run_pipeline(audio_bytes: bytes, language: str = "gu") -> dict:
    """
    Run the full pipeline: audio → transcript → list of structured reports.
    """
    result = {
        "transcript": "",
        "reports": [],
        "error": "",
        "success": False,
    }

    transcript, ok = transcribe_audio(audio_bytes, language)
    result["transcript"] = transcript

    if not ok:
        result["error"] = transcript
        return result

    reports, err = extract_structured_data(transcript)
    result["reports"] = reports

    if err:
        result["error"] = err
        return result

    result["success"] = True
    return result
