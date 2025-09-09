import os, re, tempfile, json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import openpyxl
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
try:
    from openai import OpenAI  # Optional: used only if OPENAI_API_KEY is set
except Exception:
    OpenAI = None

# ================= settings =================
EXCEL_PATH = Path("allowance.xlsx")
BUDGET_PATH = Path("budget.json")
HEADERS = ["when", "where", "amount", "memo"]  # keep your exact headers
MODEL_NAME = os.getenv("WHISPER_MODEL", "small")  # tiny/base/small/medium/large-v3
DEVICE     = os.getenv("WHISPER_DEVICE", "cpu")   # "cpu" or "cuda"
COMPUTE    = os.getenv("WHISPER_COMPUTE", "int8") # cpu:int8/int8_float32, cuda:float16

# Google Sheets settings
GOOGLE_SHEETS_CREDENTIALS_FILE = "google_credentials.json"
GOOGLE_SHEETS_URL = os.getenv("GOOGLE_SHEETS_URL", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

_whisper = None  # lazy-loaded model
_google_sheet = None  # lazy-loaded Google Sheet
_openai_client = None  # lazy-loaded OpenAI client

# ================= budget helpers =================
def load_budget():
    """Load budget settings from JSON file"""
    if BUDGET_PATH.exists():
        try:
            with open(BUDGET_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_budget(start_date: str, budget_amount: float):
    """Save budget settings to JSON file"""
    budget_data = {
        "start_date": start_date,
        "budget_amount": budget_amount,
        "created_at": datetime.now().isoformat()
    }
    with open(BUDGET_PATH, 'w', encoding='utf-8') as f:
        json.dump(budget_data, f, ensure_ascii=False, indent=2)

def get_spent_amount():
    """Calculate total spent amount from Excel/Google Sheets"""
    try:
        if EXCEL_PATH.exists():
            df = pd.read_excel(EXCEL_PATH)
            if not df.empty and 'amount' in df.columns:
                return float(df['amount'].sum())
    except Exception:
        pass
    return 0.0

def get_budget_status():
    """Get budget status: remaining amount and percentage"""
    budget = load_budget()
    if not budget:
        return None, None, None
    
    spent = get_spent_amount()
    budget_amount = budget['budget_amount']
    remaining = budget_amount - spent
    percentage = (spent / budget_amount * 100) if budget_amount > 0 else 0
    
    return remaining, percentage, budget

# ================= google sheets helpers =================
def init_google_sheets():
    global _google_sheet
    # Prefer runtime-provided URL from session state over env var
    runtime_url = None
    try:
        runtime_url = st.session_state.get("sheets_url")
    except Exception:
        runtime_url = None
    sheets_url = (runtime_url or GOOGLE_SHEETS_URL or "").strip()

    if _google_sheet is None and sheets_url:
        try:
            if os.path.exists(GOOGLE_SHEETS_CREDENTIALS_FILE):
                # Use service account credentials
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=scope)
                gc = gspread.authorize(creds)
                _google_sheet = gc.open_by_url(sheets_url).sheet1
                
                # Initialize headers if sheet is empty
                if not _google_sheet.get_all_values():
                    _google_sheet.append_row(HEADERS)
            else:
                st.warning("Google Sheets credentials file not found. Please add 'google_credentials.json' file.")
        except Exception as e:
            st.error(f"Google Sheets connection failed: {str(e)}")
    return _google_sheet

def append_to_google_sheets(when_iso: str, where: str, amount_eur: float, memo: str):
    sheet = init_google_sheets()
    if sheet:
        try:
            sheet.append_row([when_iso, where, float(amount_eur), memo])
            return True
        except Exception as e:
            st.error(f"Failed to save to Google Sheets: {str(e)}")
            return False
    return False

# ================= excel helpers =================
def init_excel():
    if not EXCEL_PATH.exists():
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(HEADERS)
        wb.save(EXCEL_PATH)

def append_row(when_iso: str, where: str, amount_eur: float, memo: str):
    # Try Google Sheets first (using runtime URL from session), fallback to Excel
    try_google = append_to_google_sheets(when_iso, where, amount_eur, memo)
    if try_google:
        st.info("📊 Saved to Google Sheets!")
        return
    
    # Fallback to local Excel file
    init_excel()
    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb.active
    ws.append([when_iso, where, float(amount_eur), memo])
    wb.save(EXCEL_PATH)
    st.info("💾 Saved to local Excel file!")

# ================= parsing =================
DATE_PATTERNS = [
    r'(?P<d>\d{1,2})[./-](?P<m>\d{1,2})[./-](?P<y>\d{4})',  # dd.mm.yyyy
    r'(?P<y>\d{4})[./-](?P<m>\d{1,2})[./-](?P<d>\d{1,2})',  # yyyy-mm-dd
]

def normalize_date(token: str) -> Optional[str]:
    token = token.strip().lower()
    # Normalize common STT artifacts: possessive, punctuation, trailing periods/commas
    token = re.sub(r"[\u2019']s\b", "", token)  # remove possessive like today's → today
    token = token.strip(" .,!?")
    
    # Handle simple words (EN + KO)
    if token in ("today", "todays", "오늘", "금일"):
        return datetime.now().strftime("%Y-%m-%d")
    if token in ("yesterday", "yesterdays", "어제"):
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Handle flexible month expressions
    now = datetime.now()
    if token in ("this month", "이번 달", "이번달"):
        return now.replace(day=1).strftime("%Y-%m-%d")
    if token in ("last month", "지난 달", "지난달"):
        if now.month == 1:
            return now.replace(year=now.year-1, month=12, day=1).strftime("%Y-%m-%d")
        else:
            return now.replace(month=now.month-1, day=1).strftime("%Y-%m-%d")
    if token in ("i don't know", "모르겠어", "모름", "don't know"):
        return now.strftime("%Y-%m-%d")  # Default to today
    
    # Korean formatted dates like 2025년 7월 8일
    km = re.fullmatch(r"(?P<y>\d{4})\s*년\s*(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일?", token)
    if km:
        try:
            return datetime(int(km.group("y")), int(km.group("m")), int(km.group("d"))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    for pat in DATE_PATTERNS:
        m = re.fullmatch(pat, token)
        if m:
            d = int(m.group("d")); mth = int(m.group("m")); y = int(m.group("y"))
            try:
                return datetime(y, mth, d).strftime("%Y-%m-%d")
            except ValueError:
                pass
    # fallback
    try:
        return pd.to_datetime(token, dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return None

def parse_amount_eur(token: str) -> Optional[float]:
    """Parse amount in euros from a possibly noisy STT string.

    Heuristics:
    - Normalize common homophones and phrases: "to you"/"to euro" → 2 euro,
      (two|too|to) → 2, (for|four) → 4, (ate|eight) → 8 when near amount.
    - Support simple number words (one..ten) and pick the LAST number in the text.
    - Default currency is euro.
    """
    t = token.strip().lower().replace("€", " euro")
    # Remove trailing punctuation
    t = t.strip(" .,!?")

    # Phrase-level normalizations
    t = re.sub(r"\bto\s+you\b", "2 euro", t)
    t = re.sub(r"\bto\s+euro\b", "2 euro", t)

    # Word-to-number mapping for common cases
    word_to_num = {
        "zero": "0", "one": "1", "two": "2", "too": "2", "to": "2",
        "three": "3", "four": "4", "for": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "ate": "8",
        "nine": "9", "ten": "10"
    }
    def replace_word_nums(match: re.Match) -> str:
        w = match.group(0)
        return word_to_num.get(w, w)
    t = re.sub(r"\b(zero|one|two|too|to|three|four|for|five|six|seven|eight|ate|nine|ten)\b", replace_word_nums, t)

    # Find all numeric tokens; take the last one
    nums = re.findall(r"-?\d+(?:[.,]\d+)?", t)
    if not nums:
        return None
    last = nums[-1].replace(",", ".")
    try:
        return round(float(last), 2)
    except Exception:
        return None

def parse_slash(raw: str):
    """
    strictly: when / where / amount / memo
    ex) today / supermarket / 35 euro / lunch
        08.07.2025 / coffee wackers / 5 euro / morning coffee
        this month / gas station / 45 euro / fuel

    The STT can mishear separators. We normalize common variants like
    spoken "slash", commas, or Korean "슬래시" into '/'.
    """
    # Normalize common spoken/written separators to '/'
    t = raw.strip()
    # Unify unicode slashes
    t = t.replace("／", "/").replace("\\", "/")
    # Remove surrounding quotes and trailing punctuation that STT may add
    t = re.sub(r"^[\"']+|[\"']+$", "", t)
    # Replace commas with slashes
    t = re.sub(r"\s*,\s*", " / ", t)
    # Replace spoken words meaning slash (en/ko variants)
    t = re.sub(r"\bslash\b", "/", t, flags=re.IGNORECASE)
    t = re.sub(r"슬래시|슬레시|슬래쉬", "/", t)
    # Collapse multiple separators/spaces
    t = re.sub(r"\s*\/\s*", " / ", t)
    t = re.sub(r"\s+", " ", t).strip()

    parts = [p.strip() for p in t.split("/") if p.strip()]
    # Fallback: exactly four space-separated tokens with 3rd token numeric → when where amount memo
    if len(parts) == 1 and "/" not in t:
        space_tokens = t.split()
        if len(space_tokens) == 4 and re.fullmatch(r"-?\d+(?:[.,]\d+)?(?:\s*(?:euro|eur))?", space_tokens[2]):
            parts = [space_tokens[0], space_tokens[1], space_tokens[2], space_tokens[3]]
    if len(parts) != 4:
        raise ValueError("Use 4 parts: when / where / amount / memo")
    when_tok, where, amount_tok, memo = parts
    when_iso = normalize_date(when_tok)
    if not when_iso:
        raise ValueError(f"Invalid date: '{when_tok}'")
    amount = parse_amount_eur(amount_tok)
    if amount is None:
        raise ValueError(f"Invalid amount: '{amount_tok}' (use e.g. '35 euro')")
    return when_iso, where, amount, memo

# ================= stt =================
def load_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE)
    return _whisper

def transcribe_file(tmp_path: str, language: str = "en") -> str:
    model = load_whisper()
    segments, info = model.transcribe(tmp_path, language=language, vad_filter=True)
    return "".join(seg.text for seg in segments).strip()

def load_openai_client():
    global _openai_client
    if _openai_client is None and OPENAI_API_KEY and OpenAI is not None:
        try:
            _openai_client = OpenAI(api_key=OPENAI_API_KEY)
        except Exception as e:
            st.warning(f"OpenAI client init failed: {e}")
    return _openai_client

def llm_extract_fields(text: str) -> Optional[tuple]:
    """Use an LLM to robustly extract (when, where, product, amount).
    Returns tuple or None if extraction fails.
    """
    client = load_openai_client()
    if not client:
        return None
    try:
        system = (
            "You extract purchase records as 4 fields: when(ISO yyyy-mm-dd or 'today'/'yesterday'), "
            "where, product, amount(eur as number). Reply ONLY as JSON: "
            "{\"when\":...,\"where\":...,\"product\":...,\"amount\":...}."
        )
        user = f"Text: {text}"
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0
        )
        content = resp.choices[0].message.content
        import json
        data = json.loads(content)
        when_tok = str(data.get("when", "")).strip()
        where = str(data.get("where", "")).strip()
        product = str(data.get("product", "")).strip()
        amount_val = data.get("amount")
        when_iso = normalize_date(when_tok)
        if when_iso is None:
            return None
        try:
            amount = float(amount_val)
        except Exception:
            amount = parse_amount_eur(str(amount_val))
        if amount is None:
            return None
        return when_iso, where, amount, memo or ""
    except Exception as e:
        st.warning(f"LLM parse failed: {e}")
        return None

# ================= streamlit ui =================
st.set_page_config(page_title="Allowance Ingest (EUR)", page_icon="💶", layout="centered")
st.title("💶 Allowance Ingest (EUR) — Test App")
st.caption("Type or speak the command in **slash format**: `when / where / amount / memo` (Euro only).")

# ================= budget status display =================
remaining, percentage, budget = get_budget_status()
if budget:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("💰 Budget", f"€{budget['budget_amount']:.2f}")
    with col2:
        st.metric("💸 Spent", f"€{budget['budget_amount'] - remaining:.2f}")
    with col3:
        st.metric("💵 Remaining", f"€{remaining:.2f}")
    
    # Progress bar
    progress_color = "green" if percentage < 70 else "orange" if percentage < 90 else "red"
    st.progress(percentage / 100)
    st.caption(f"Budget usage: {percentage:.1f}%")
else:
    st.info("💡 Set your budget in 'Budget Management' section to track spending!")

with st.expander("Text input", expanded=True):
    txt = st.text_input("Example", "today / supermarket / 35 euro / lunch")
    if st.button("Save from text"):
        try:
            when_iso, where, amount, memo = parse_slash(txt)
            append_row(when_iso, where, amount, memo)
            st.success(f"Saved → {when_iso} | {where} | €{amount:.2f} | {memo}")
        except Exception as e:
            st.error(str(e))

with st.expander("🎤 Real-time Recording", expanded=True):
    st.write("**Record directly from your microphone** - say it in slash format (e.g., 'today / supermarket / 35 euro / lunch').")
    
    # Real-time recording
    audio_data = st.audio_input("Record your voice")
    
    if audio_data is not None:
        # Save the recorded audio to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            f.write(audio_data.read())
            tmp_path = f.name
        
        try:
            # Transcribe the recorded audio
            text = transcribe_file(tmp_path, language="en")
            st.info(f"🎯 Transcribed: **{text or '(empty)'}**")
            
            if text:
                # Try LLM-assisted parse first if available
                parsed = llm_extract_fields(text) if st.session_state.get("use_llm_parse") else None
                if parsed is not None:
                    when_iso, where, amount, memo = parsed
                else:
                    when_iso, where, amount, memo = parse_slash(text)
                append_row(when_iso, where, amount, memo)
                st.success(f"✅ Saved → {when_iso} | {where} | €{amount:.2f} | {memo}")
            else:
                st.warning("No speech detected. Please try speaking more clearly.")
                
        except Exception as e:
            st.error(f"Error: {str(e)}")
        finally:
            try: 
                os.remove(tmp_path)
            except Exception: 
                pass

with st.expander("📁 Audio File Upload"):
    st.write("Upload a pre-recorded audio file where you **say it in slash format** (e.g., 'today / supermarket / 35 euro / lunch').")
    audio = st.file_uploader("Audio file", type=["wav", "mp3", "m4a", "ogg"])
    lang = st.selectbox("Language", ["en"], index=0)
    show_text = st.checkbox("Show transcribed text", value=True)
    if st.button("Transcribe & Save", disabled=audio is None):
        if not audio:
            st.error("Please upload an audio file.")
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(audio.name)[-1] or ".wav") as f:
                f.write(audio.read())
                tmp_path = f.name
            try:
                text = transcribe_file(tmp_path, language=lang)
                if show_text:
                    st.info(f"Transcribed: {text or '(empty)'}")
                if not text:
                    raise ValueError("Transcription failed or produced empty text.")
                parsed = llm_extract_fields(text) if st.session_state.get("use_llm_parse") else None
                if parsed is not None:
                    when_iso, where, amount, memo = parsed
                else:
                    when_iso, where, amount, memo = parse_slash(text)
                append_row(when_iso, where, amount, memo)
                st.success(f"Saved → {when_iso} | {where} | €{amount:.2f} | {memo}")
            except Exception as e:
                st.error(str(e))
            finally:
                try: os.remove(tmp_path)
                except Exception: pass

st.markdown("---")

# ================= budget configuration =================
with st.expander("💰 Budget Management", expanded=False):
    st.write("**Set and track your monthly budget**")
    
    budget = load_budget()
    
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input(
            "Budget Start Date",
            value=datetime.strptime(budget['start_date'], '%Y-%m-%d').date() if budget else datetime.now().date(),
            help="When does your budget period start?"
        )
    
    with col2:
        budget_amount = st.number_input(
            "Monthly Budget (EUR)",
            min_value=0.0,
            value=budget['budget_amount'] if budget else 100.0,
            step=10.0,
            help="Your total monthly budget in euros"
        )
    
    if st.button("💾 Save Budget"):
        save_budget(start_date.strftime('%Y-%m-%d'), budget_amount)
        st.success(f"✅ Budget saved: €{budget_amount:.2f} starting {start_date}")
        st.rerun()
    
    if budget:
        if st.button("🗑️ Delete Budget"):
            if BUDGET_PATH.exists():
                BUDGET_PATH.unlink()
            st.success("✅ Budget deleted")
            st.rerun()
        
        # Budget status display
        st.markdown("---")
        st.write("**Current Budget Status**")
        remaining, percentage, _ = get_budget_status()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("💰 Total Budget", f"€{budget['budget_amount']:.2f}")
        with col2:
            st.metric("💸 Spent", f"€{budget['budget_amount'] - remaining:.2f}")
        with col3:
            st.metric("💵 Remaining", f"€{remaining:.2f}")
        
        # Progress bar
        progress_color = "green" if percentage < 70 else "orange" if percentage < 90 else "red"
        st.progress(percentage / 100)
        st.caption(f"Budget usage: {percentage:.1f}%")

st.markdown("---")

# Google Sheets configuration section
with st.expander("⚙️ Google Sheets Configuration"):
    st.write("**Connect to your Google Sheets for real-time sync**")
    
    # Google Sheets URL input
    sheets_url = st.text_input(
        "Google Sheets URL", 
        value=st.session_state.get("sheets_url", GOOGLE_SHEETS_URL),
        help="Copy the URL from your Google Sheets (e.g., https://docs.google.com/spreadsheets/d/...)",
        placeholder="https://docs.google.com/spreadsheets/d/..."
    )

    # Persist URL to session for runtime use
    if sheets_url:
        st.session_state["sheets_url"] = sheets_url.strip()
    
    # Credentials file upload
    st.write("**Upload Google Service Account Credentials**")
    credentials_file = st.file_uploader(
        "Upload google_credentials.json", 
        type=['json'],
        help="Download from Google Cloud Console > Service Accounts"
    )
    
    service_account_email = None
    if credentials_file:
        # Save uploaded credentials
        with open(GOOGLE_SHEETS_CREDENTIALS_FILE, "wb") as f:
            f.write(credentials_file.getbuffer())
        st.success("✅ Credentials uploaded! Restart is not required.")
        # Read and show the service account email to share your sheet with
        try:
            import json
            credentials_file.seek(0)
            data = json.load(credentials_file)
            service_account_email = data.get("client_email")
        except Exception:
            service_account_email = None
    else:
        # If file already exists, try reading email from it
        try:
            import json
            if os.path.exists(GOOGLE_SHEETS_CREDENTIALS_FILE):
                with open(GOOGLE_SHEETS_CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    service_account_email = data.get("client_email")
        except Exception:
            service_account_email = None

    if service_account_email:
        st.info(f"Share your Google Sheet with: {service_account_email} (Editor)")
    
    # Test connection
    if st.button("Test Google Sheets Connection"):
        url_ok = bool(st.session_state.get("sheets_url"))
        creds_ok = os.path.exists(GOOGLE_SHEETS_CREDENTIALS_FILE)
        if url_ok and creds_ok:
            # Reset cached connection to force reconnect with latest URL/creds
            _google_sheet = None
            sheet = init_google_sheets()
            if sheet:
                st.success("🎉 Connected to Google Sheets successfully!")
                st.write(f"Sheet title: {sheet.title}")
            else:
                st.error("❌ Failed to connect to Google Sheets")
        else:
            missing = []
            if not url_ok: missing.append("URL")
            if not creds_ok: missing.append("credentials")
            st.warning("⚠️ Please provide: " + ", ".join(missing))

st.markdown("---")

with st.expander("🧠 LLM Parser (optional)", expanded=False):
    st.write("Use an LLM to better understand messy speech. Requires OPENAI_API_KEY.")
    use_llm = st.checkbox("Enable LLM-assisted parsing", value=st.session_state.get("use_llm_parse", False))
    st.session_state["use_llm_parse"] = use_llm
    if use_llm and not OPENAI_API_KEY:
        st.warning("Set environment variable OPENAI_API_KEY to use this feature.")

st.caption("Data is saved to Google Sheets (if configured) or local allowance.xlsx file (columns: when | where | amount | memo).")
