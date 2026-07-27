"""
app.py — Voice Site Reporter
Run with: python -m streamlit run app.py

Handles ONE voice note describing MULTIPLE updates — a supervisor rattling off
several machines/sites/activities back to back mid-shift gets split into
separate editable entries, all logged together.
"""

import streamlit as st
import pandas as pd
import os
import io
import time
from dotenv import load_dotenv
from pipeline import run_pipeline, SiteReport
from sheets_logger import log_reports, get_recent_entries

load_dotenv()

st.set_page_config(page_title="Site Voice Reporter", page_icon="🏗️", layout="centered")

st.markdown("""
<style>
  .transcript-box {
    background:#f0f4f8; border-left:3px solid #4A90D9;
    border-radius:4px; padding:0.6rem 0.9rem; font-style:italic; margin:0.5rem 0;
  }
  .anomaly-banner {
    background:#fff3cd; border:1.5px solid #ffc107;
    border-radius:8px; padding:0.6rem 0.9rem; margin:0.4rem 0; font-weight:500; font-size:14px;
  }
  .success-banner {
    background:#d1e7dd; border:1.5px solid #198754;
    border-radius:8px; padding:0.75rem 1rem; margin:0.5rem 0;
  }
  .entry-card {
    border:1px solid #dee2e6; border-radius:10px;
    padding:0.9rem 1rem 0.3rem; margin:0.6rem 0; background:#fcfcfd;
  }
  .entry-badge {
    display:inline-block; background:#2C3E50; color:white;
    border-radius:20px; padding:2px 12px; font-size:12px; font-weight:600; margin-bottom:6px;
  }
</style>
""", unsafe_allow_html=True)


def amplify_audio(audio_bytes: bytes, gain: float = 2.5) -> bytes:
    """Boost WAV volume before sending to Whisper."""
    try:
        import wave, array
        buf = io.BytesIO(audio_bytes)
        with wave.open(buf, 'rb') as wf:
            params, raw, sampwidth = wf.getparams(), wf.readframes(wf.getnframes()), wf.getsampwidth()
        if sampwidth == 2:
            samples = array.array('h', raw)
            raw = array.array('h', [max(-32768, min(32767, int(s * gain))) for s in samples]).tobytes()
        out = io.BytesIO()
        with wave.open(out, 'wb') as wf_out:
            wf_out.setparams(params)
            wf_out.writeframes(raw)
        return out.getvalue()
    except Exception:
        return audio_bytes


def process_recording(audio_bytes: bytes, lang_code: str):
    """Run pipeline and store ALL extracted entries with a fresh run_id."""
    result = run_pipeline(audio_bytes, lang_code)
    st.session_state["result"] = {
        "run_id": str(time.time()),
        "transcript": result["transcript"],
        "reports": [r.model_dump() for r in result["reports"]],
        "error": result["error"],
    }


def render_result():
    data = st.session_state.get("result")
    if not data:
        return

    transcript = data["transcript"]
    reports = data["reports"]
    err = data["error"]
    run_id = data["run_id"]

    if not transcript:
        st.error(err or "No speech detected — try speaking louder or increasing mic boost.")
        return

    st.markdown(f'<div class="transcript-box">"{transcript}"</div>', unsafe_allow_html=True)
    if err:
        st.warning(err)

    if not reports:
        st.warning("No entries could be extracted from this transcript.")
        return

    n = len(reports)
    if n > 1:
        st.markdown(f"### 📋 {n} entries found in this recording")
        st.caption("Each update from your voice note is shown separately below — edit any of them before logging.")
    else:
        st.markdown("### 📋 Entry")

    # ── Render each extracted entry as its own editable card ────
    to_remove = []
    for i, report_dict in enumerate(reports):
        key_prefix = f"{run_id}_{i}"

        st.markdown('<div class="entry-card">', unsafe_allow_html=True)
        if n > 1:
            st.markdown(f'<span class="entry-badge">Entry {i+1} of {n}</span>', unsafe_allow_html=True)

        report = SiteReport(**report_dict)
        if report.is_anomaly:
            st.markdown(
                f'<div class="anomaly-banner">🚨 Diesel = {report.quantity} {report.unit} '
                f'— exceeds 100L. Please verify.</div>', unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            report_dict["site_name"] = st.text_input("Site", report_dict.get("site_name") or "", key=f"site_{key_prefix}")
            report_dict["machine_id"] = st.text_input("Machine", report_dict.get("machine_id") or "", key=f"machine_{key_prefix}")
            report_dict["activity"] = st.text_input("Activity", report_dict.get("activity") or "", key=f"activity_{key_prefix}")
            report_dict["reported_by"] = st.text_input("Reported by", report_dict.get("reported_by") or "", key=f"by_{key_prefix}")
        with c2:
            report_dict["material"] = st.text_input("Material", report_dict.get("material") or "", key=f"material_{key_prefix}")
            q = st.number_input("Quantity", value=float(report_dict.get("quantity") or 0), min_value=0.0, key=f"qty_{key_prefix}")
            report_dict["quantity"] = q if q > 0 else None
            report_dict["unit"] = st.text_input("Unit", report_dict.get("unit") or "", key=f"unit_{key_prefix}")
            report_dict["notes"] = st.text_input("Notes", report_dict.get("notes") or "", key=f"notes_{key_prefix}")

        if n > 1:
            if st.button(f"🗑️ Remove entry {i+1}", key=f"remove_{key_prefix}"):
                to_remove.append(i)

        st.markdown('</div>', unsafe_allow_html=True)

    # Apply removals
    if to_remove:
        st.session_state["result"]["reports"] = [
            r for i, r in enumerate(reports) if i not in to_remove
        ]
        st.rerun()

    st.session_state["result"]["reports"] = reports

    # ── Log all remaining entries at once ────────────────────────
    remaining = len(st.session_state["result"]["reports"])
    b1, b2 = st.columns([3, 1])
    with b1:
        label = f"✅ Confirm & Log {remaining} {'Entries' if remaining != 1 else 'Entry'}"
        if st.button(label, type="primary", use_container_width=True):
            try:
                final_reports = [SiteReport(**r) for r in st.session_state["result"]["reports"]]
                log_reports(final_reports, transcript, source="streamlit")
                st.markdown(
                    f'<div class="success-banner">✅ {remaining} '
                    f'{"entries" if remaining != 1 else "entry"} logged to Google Sheets!</div>',
                    unsafe_allow_html=True,
                )
                del st.session_state["result"]
                st.rerun()
            except FileNotFoundError:
                st.error("credentials.json not found — see SETUP_GUIDE.md")
            except Exception as e:
                st.error(f"❌ {e}")
    with b2:
        if st.button("🗑️ Discard All", use_container_width=True):
            del st.session_state["result"]
            st.rerun()


# ══════════════════════════════════════════
# MAIN UI
# ══════════════════════════════════════════

st.title("🏗️ Site Voice Reporter")

missing = []
if not os.getenv("GEMINI_API_KEY"): missing.append("GEMINI_API_KEY")
if not os.getenv("GROQ_API_KEY"):   missing.append("GROQ_API_KEY")
if not os.path.exists("credentials.json"): missing.append("credentials.json")
if missing:
    st.warning(f"⚙️ Missing: {', '.join(missing)} — see SETUP_GUIDE.md")

lang_label = st.radio("Language", ["Gujarati", "Hindi"], horizontal=True, label_visibility="collapsed")
lang_code = "gu" if lang_label == "Gujarati" else "hi"

gain = st.slider("Mic Boost", 1.0, 6.0, 2.5, 0.5)

st.caption("💬 Tip: you can report multiple updates in one recording — e.g. "
           "\"Machine 2 diesel bharyo 40 litre Kathwada, ane Machine 5 nu kaam pura thayu Sanand\"")

audio_value = st.audio_input("Record your report")

if audio_value is not None:
    raw_bytes = audio_value.read()
    boosted = amplify_audio(raw_bytes, gain) if gain != 1.0 else raw_bytes

    if st.button("🔄 Transcribe & Extract", type="primary", use_container_width=True):
        with st.spinner("Transcribing..."):
            process_recording(boosted, lang_code)

render_result()

st.divider()
st.markdown("### 📋 Recent Reports")
try:
    recent = get_recent_entries(10)
    if recent:
        cols = ["Timestamp","Site","Machine","Activity","Material","Qty","Unit","By","Notes","⚠️","Transcript","Source"]
        padded = [r + [""] * (len(cols) - len(r)) for r in recent]
        df = pd.DataFrame(padded, columns=cols)
        st.dataframe(df[["Timestamp","Site","Machine","Activity","Material","Qty","Unit","⚠️"]],
                     use_container_width=True, hide_index=True)
    else:
        st.info("No entries yet.")
except FileNotFoundError:
    st.info("Connect Google Sheets to see recent entries.")
except Exception as e:
    st.warning(f"Could not load entries: {e}")
