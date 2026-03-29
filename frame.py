"""
=============================================================
  AUTONOMOUS AI SALES & REVENUE ENGINE
  ET GenAI Hackathon 2025
=============================================================
  INSTALL:  pip install streamlit pandas requests
  RUN:      streamlit run sales_engine.py

  SETUP:
  1. Paste apifreellm key at API_KEY (line ~50)
  2. Set EMAIL_USER and EMAIL_PASS below (lines ~54-55)
     Outlook personal: just your password
     Work/School Microsoft 365: may need App Password or SMTP AUTH enabled
  3. Upload your CSV (only 6 cols needed — see Tab 4)
  4. Describe your product → Run Engine
=============================================================
"""

import streamlit as st

# ── MUST BE ABSOLUTE FIRST STREAMLIT CALL ─────────────────
st.set_page_config(
    page_title="AI Sales Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

import pandas as pd
import json
import random
import re
import time
import requests
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date
from pathlib import Path

# =============================================================
# ── CONFIGURATION — fill these in ────────────────────────────
# =============================================================

# apifreellm.com — sign in with Google → copy key
API_KEY      = "apf_qwy2n598j33z8p14ri8omuph"
API_URL      = "https://apifreellm.com/api/v1/chat"
RATE_LIMIT   = 27          # free tier: 1 req/25s + 2s buffer
MAX_RETRIES  = 3           # max retries per agent call before skip

# Outlook SMTP — use your real Outlook email + password
# If using Microsoft 365 work account, may need App Password
# Settings: login.microsoftonline.com → Security → App Passwords
EMAIL_USER    = "heshashank789@outlook.com"
EMAIL_PASS    = "heshashank789"
SMTP_SERVER   = "smtp.office365.com"
SMTP_PORT     = 587


# =============================================================
# ── FILE PATHS ────────────────────────────────────────────────
# =============================================================
PIPELINE_FILE  = "pipeline_live.csv"
AGENT_LOG_FILE = "agent_logs.json"
REPORTS_DIR    = "reports"
Path(REPORTS_DIR).mkdir(exist_ok=True)

# =============================================================
# ── COLUMN SCHEMA — 37 columns ───────────────────────────────
# =============================================================
# YOUR 6 INPUT COLUMNS (flexible header matching — see load_csv)
INPUT_COLS = ["lead_id","full_name","company_name","role_title","email","phone"]

# SYSTEM COLUMNS — all filled by agents
SYSTEM_COLS = {
    # Research (10)
    "industry":"", "company_size":"", "business_model":"",
    "company_summary":"", "growth_signals":"", "pain_point_1":"",
    "tech_stack_inferred":"", "conversation_hook":"",
    "best_approach_angle":"", "research_completed_at":"",
    # Qualification (5)
    "qualification_score":"", "qualification_tier":"",
    "tier_reasoning":"", "skip_flag":"", "skip_reason":"",
    # Pipeline Manager (4)
    "current_stage":"New", "days_in_current_stage":0,
    "pipeline_velocity":"", "stage_history":"New",
    # Outreach + Personalization (3)
    "outreach_subject":"", "outreach_sent_at":"", "follow_up_number":0,
    # Monitoring (5)
    "pipeline_status":"", "urgency_score":"",
    "positive_signals":"", "negative_signals":"", "days_since_contact":"",
    # Recovery (4)
    "recovery_attempts":0, "recovery_strategy":"",
    "recovery_confidence_pct":"", "walk_away_flag":"",
    # Escalation (3)
    "escalation_flag":"", "escalation_urgency":"", "escalation_reason":"",
    # System (2)
    "last_agent_run":"", "last_updated_at":"",
}

ALL_COLS = INPUT_COLS + list(SYSTEM_COLS.keys())   # 37 total

# =============================================================
# ── SESSION STATE ─────────────────────────────────────────────
# =============================================================
def init_state():
    defaults = {
        "pipeline_df":        None,
        "original_path":      None,
        "agent_logs":         [],
        "agent_statuses": {a:"idle" for a in [
            "Manager","Research","Qualification","Pipeline Manager",
            "Outreach","Personalization","Monitoring","Recovery",
            "Escalation","Marketing Intelligence","Reporting"
        ]},
        "agent_counts": {a:0 for a in [
            "Manager","Research","Qualification","Pipeline Manager",
            "Outreach","Personalization","Monitoring","Recovery",
            "Escalation","Marketing Intelligence","Reporting"
        ]},
        "active_agent":       None,      # currently running agent name
        "data_flow_log":      [],        # [(from_agent, to_agent, lead_id, timestamp)]
        "manager_reasoning":  [],
        "last_report":        None,
        "last_marketing":     None,
        "engine_running":     False,
        "run_complete":       False,
        "_last_api_call":     0,
        "product_context":    "",
        "run_errors":         [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# =============================================================
# ── FLEXIBLE CSV LOADER ───────────────────────────────────────
# =============================================================

# Maps common alternative header names → our standard names
HEADER_ALIASES = {
    "lead_id":      ["id","lead id","leadid","lead_id","#"],
    "full_name":    ["name","full name","fullname","full_name",
                     "contact name","contact","person"],
    "company_name": ["company","company name","org","organisation",
                     "organization","firm","business","company_name"],
    "role_title":   ["role","title","job title","position","designation",
                     "job","role_title","jobtitle"],
    "email":        ["email","email address","mail","e-mail","emailid"],
    "phone":        ["phone","phone number","mobile","contact number",
                     "cell","telephone","ph","phone_number","mobile_number"],
}

def normalise_headers(df: pd.DataFrame) -> pd.DataFrame:
    """Map whatever headers user has → our standard column names."""
    col_map = {}
    df_cols_lower = {c.lower().strip(): c for c in df.columns}
    for standard, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias.lower() in df_cols_lower:
                col_map[df_cols_lower[alias.lower()]] = standard
                break
    return df.rename(columns=col_map)


def load_csv(uploaded_file) -> tuple[pd.DataFrame, list]:
    """
    Load CSV with flexible headers.
    Returns (dataframe, list_of_warnings).
    Never hard-stops — skips bad rows and warns.
    """
    warnings = []
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Could not read CSV: {e}")
        st.stop()

    df = normalise_headers(df)

    # Check which required cols are still missing after normalisation
    missing = [c for c in INPUT_COLS if c not in df.columns]
    if missing:
        warnings.append(
            f"Could not find columns: {missing}. "
            f"Creating them empty — fill manually or regenerate data."
        )
        for c in missing:
            df[c] = ""

    # Add all system columns with defaults
    for col, default in SYSTEM_COLS.items():
        if col not in df.columns:
            df[col] = default

    # Enforce column order
    df = df.reindex(columns=ALL_COLS, fill_value="")

    # Auto-generate missing lead_ids
    for i, row in df.iterrows():
        if not str(row["lead_id"]).strip():
            df.at[i, "lead_id"] = f"L{1000+i}"

    # Flag rows with no email — mark as incomplete, don't skip entirely
    no_email = df["email"].astype(str).str.strip() == ""
    if no_email.any():
        warnings.append(
            f"{no_email.sum()} leads have no email — "
            f"outreach will be skipped for these leads."
        )
        df.loc[no_email, "skip_flag"]   = "true"
        df.loc[no_email, "skip_reason"] = "No email address"

    # Flag rows with no company name
    no_company = df["company_name"].astype(str).str.strip() == ""
    if no_company.any():
        warnings.append(
            f"{no_company.sum()} leads have no company name — "
            f"research quality will be lower for these leads."
        )

    # Initialise timestamps
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    df["current_stage"]         = "New"
    df["stage_history"]         = "New"
    df["last_updated_at"]       = now
    df["days_in_current_stage"] = 0

    return df, warnings


def save_pipeline(df: pd.DataFrame):
    """Save to pipeline_live.csv AND original uploaded file."""
    df = df.copy()
    df["last_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    df.to_csv(PIPELINE_FILE, index=False)
    orig = st.session_state.get("original_path")
    if orig and os.path.exists(orig):
        try:
            df.to_csv(orig, index=False)
        except Exception:
            pass   # don't crash if file is locked


def update_lead(df: pd.DataFrame, lead_id: str, updates: dict) -> pd.DataFrame:
    """Update one lead's columns and immediately save both files."""
    mask = df["lead_id"].astype(str) == str(lead_id)
    if not mask.any():
        return df
    for col, val in updates.items():
        if col in df.columns:
            df.loc[mask, col] = val
    df.loc[mask, "last_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_pipeline(df)
    return df

# =============================================================
# ── AGENT STATUS HELPERS ──────────────────────────────────────
# =============================================================

def set_agent(name: str, status: str, leads_done: int = 0):
    st.session_state["agent_statuses"][name] = status
    st.session_state["active_agent"] = name if status == "running" else None
    if leads_done:
        st.session_state["agent_counts"][name] += leads_done

def log_flow(from_agent: str, to_agent: str, lead_id: str = "all"):
    st.session_state["data_flow_log"].append({
        "from":      from_agent,
        "to":        to_agent,
        "lead_id":   lead_id,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    })

def add_reasoning(line: str):
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state["manager_reasoning"].append(f"[{ts}] {line}")

def log_error(agent: str, lead_id: str, error: str):
    st.session_state["run_errors"].append({
        "agent": agent, "lead_id": lead_id,
        "error": error, "time": datetime.now().strftime("%H:%M:%S")
    })

# =============================================================
# ── RATE-LIMITED LLM CALL ─────────────────────────────────────
# =============================================================

def call_llm(prompt: str, expect_json: bool = True,
             agent_name: str = "", lead_id: str = "") -> dict | str:
    """
    POST to apifreellm with:
    - Auto rate-limit wait
    - Max 3 retries on failure
    - Robust JSON extraction
    - Never raises — always returns {} or "" on failure
    """
    if API_KEY == "YOUR_APIFREELLM_KEY_HERE":
        st.error("API key missing — paste apifreellm key at line 50")
        st.stop()

    # Rate limit
    now  = time.time()
    last = st.session_state.get("_last_api_call", 0)
    wait = RATE_LIMIT - (now - last)
    if wait > 0:
        time.sleep(wait)

    raw_text = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                API_URL,
                headers={
                    "Content-Type":  "application/json",
                    "Authorization": f"Bearer {API_KEY}",
                },
                json={"message": prompt},
                timeout=90,
            )
            st.session_state["_last_api_call"] = time.time()

            if not resp.ok:
                raise ValueError(f"HTTP {resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            if not data.get("success", False):
                raise ValueError(f"API success=false: {str(data)[:200]}")

            raw_text = data.get("response", "").strip()

            if not expect_json:
                _save_log(agent_name, lead_id, True, len(raw_text))
                return raw_text

            # Extract JSON — handles fenced and bare
            fence = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
            json_str = fence.group(1) if fence else raw_text
            if not fence:
                brace = re.search(r"\{.*\}", raw_text, re.DOTALL)
                json_str = brace.group(0) if brace else raw_text

            result = json.loads(json_str)
            _save_log(agent_name, lead_id, True, len(raw_text))
            return result

        except json.JSONDecodeError:
            if attempt == MAX_RETRIES:
                log_error(agent_name, lead_id, f"JSON parse failed after {MAX_RETRIES} attempts")
                _save_log(agent_name, lead_id, False, 0)
                return {}
            time.sleep(RATE_LIMIT)   # wait before retry

        except Exception as e:
            err = str(e)
            if attempt == MAX_RETRIES:
                log_error(agent_name, lead_id, err)
                _save_log(agent_name, lead_id, False, 0)
                return {} if expect_json else ""
            time.sleep(RATE_LIMIT)

    return {} if expect_json else ""


def _save_log(agent: str, lead_id: str, success: bool, resp_len: int):
    entry = {
        "agent":    agent, "lead_id": lead_id,
        "success":  success, "resp_len": resp_len,
        "time":     datetime.now().strftime("%H:%M:%S"),
    }
    st.session_state["agent_logs"].append(entry)
    try:
        existing = []
        if os.path.exists(AGENT_LOG_FILE):
            with open(AGENT_LOG_FILE) as f:
                existing = json.load(f)
        existing.append(entry)
        with open(AGENT_LOG_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass

# =============================================================
# ── REAL EMAIL SENDER ─────────────────────────────────────────
# =============================================================

def send_email(to_address: str, subject: str, body: str,
               from_name: str = "AI Sales Engine") -> tuple[bool, str]:
    """
    Send real email via Outlook/Office365 SMTP (STARTTLS on port 587).
    Returns (success: bool, message: str).
    """
    if EMAIL_USER == "your_email@outlook.com":
        return False, "Email not configured — set EMAIL_USER and EMAIL_PASS in code"

    if not to_address or "@" not in str(to_address):
        return False, f"Invalid email address: {to_address}"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{from_name} <{EMAIL_USER}>"
        msg["To"]      = to_address

        msg.attach(MIMEText(body, "plain"))
        html_body = (
            "<html><body style='font-family:Arial,sans-serif;"
            "max-width:600px;margin:0 auto;padding:20px;color:#333'>"
            + body.replace("\n", "<br>")
            + "</body></html>"
        )
        msg.attach(MIMEText(html_body, "html"))

        # Outlook requires SMTP + STARTTLS (NOT SMTP_SSL)
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, to_address, msg.as_string())
        server.quit()

        return True, f"Sent to {to_address}"

    except smtplib.SMTPAuthenticationError:
        return False, (
            "Outlook auth failed. Check EMAIL_USER and EMAIL_PASS. "
            "If using work/school account, enable SMTP AUTH in Microsoft 365 admin."
        )
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {str(e)}"
    except Exception as e:
        return False, f"Send failed: {str(e)}"

# =============================================================
# ── PRODUCT CONTEXT INJECTION ─────────────────────────────────
# =============================================================

def get_product_context() -> str:
    """Returns the product/service context set by user in UI."""
    # key="product_context" in text_area writes directly here
    ctx = str(st.session_state.get("product_context", "")).strip()
    if not ctx:
        return "a B2B SaaS solution (product not specified — please set it in the sidebar)"
    return ctx

# =============================================================
# ── AGENT PROMPTS ─────────────────────────────────────────────
# All prompts inject {product_context} dynamically
# =============================================================

def prompt_manager(new_count, contacted_count, at_risk_count,
                    lead_ids, product_context, total):
    return f"""
You are the Manager Agent for a B2B sales engine selling: {product_context}

Pipeline snapshot:
- Total leads: {total}
- New leads (need full pipeline): {new_count}
- Active/Contacted leads (need monitoring): {contacted_count}
- At-risk leads (need recovery): {at_risk_count}
- All lead IDs: {lead_ids}

Your job: Decide the execution order for these agents:
Research, Qualification, Pipeline Manager, Outreach, Personalization,
Monitoring, Recovery, Escalation, Marketing Intelligence, Reporting

Rules:
- Research + Qualification must run before Outreach
- Pipeline Manager runs after each batch
- Monitoring runs before Recovery
- Marketing Intelligence + Reporting always last
- New leads: Research → Qualification → Outreach → Personalization
- Active leads: Monitoring → Recovery if flagged

Return ONLY valid JSON (keep it short):
{{
  "reasoning_trail": [
    "one sentence explaining your key decisions"
  ],
  "priority_order": ["Research","Qualification","Pipeline Manager","Outreach","Personalization","Monitoring","Recovery","Escalation","Marketing Intelligence","Reporting"],
  "notes": "any special handling needed"
}}
"""

def prompt_research(lead, product_context, timestamp):
    return f"""
You are the Research Agent for a company selling: {product_context}

Enrich this lead. Infer logically from company name, industry, role.
Do NOT hallucinate specific facts. Think like a human analyst
who spent 20 minutes on LinkedIn and Crunchbase.
Everything must be specific to THIS company and THIS person.

PRODUCE:
- industry, sub_industry, company_size (Startup/SMB/Mid-market/Enterprise)
- business_model (B2B/B2C/B2B2C/Marketplace)  
- company_summary: MAXIMUM 15 WORDS — count strictly — plain language not tagline
- growth_signals: inferred stage, hiring signals, recent events
- pain_point_1: the single most acute pain THIS ROLE faces in THIS INDUSTRY
  that our product ({product_context}) could solve — be specific
- tech_stack_inferred: tools they likely use, gaps relevant to our product
- conversation_hook: one specific non-generic opener for this person
- best_approach_angle: what they care about most given their role

STRICT RULES:
- Never say "may benefit from" or "could potentially"
- company_summary must be 15 words or fewer — hard limit
- If cannot infer something write "insufficient data"
- If company_name is empty, work with role_title and industry only

Return ONLY valid JSON:
{{
  "lead_id": "{lead.get('lead_id','')}",
  "industry": "",
  "company_size": "Startup|SMB|Mid-market|Enterprise",
  "business_model": "B2B|B2C|B2B2C|Marketplace",
  "company_summary": "max 15 words",
  "growth_signals": "",
  "pain_point_1": "",
  "tech_stack_inferred": "",
  "conversation_hook": "",
  "best_approach_angle": "",
  "research_completed_at": "{timestamp}"
}}

Lead: {json.dumps(lead)}
"""

def prompt_qualification(lead, research, product_context):
    return f"""
You are the Qualification Agent for a company selling: {product_context}

Score this lead with ruthless honesty. No inflating scores.

SCORE each 0-10:
- budget_fit (30%): can this company afford our product
- authority (25%): is this person a decision maker
- need (25%): how acute is their pain for our specific product
- timeline (10%): likely to decide in 90 days
- engagement_potential (10%): will they respond to cold email

OVERALL = (budget*0.30 + authority*0.25 + need*0.25 + timeline*0.10 + engagement*0.10) * 10

TIER: Hot=75+, Warm=50-74, Cold=below 50

SKIP FLAG = true if:
- No meaningful pain AND budget_fit below 4
- Zero buying influence for this company size
- Industry has zero fit for: {product_context}
Write specific skip_reason.

If lead has no email — set skip_flag=false, note in tier_reasoning
that outreach will be skipped but lead stays in pipeline.

Return ONLY valid JSON:
{{
  "lead_id": "{lead.get('lead_id','')}",
  "scores": {{
    "budget_fit": 0, "authority": 0, "need": 0,
    "timeline": 0, "engagement_potential": 0
  }},
  "qualification_score": 0,
  "qualification_tier": "Hot|Warm|Cold",
  "tier_reasoning": "one sentence",
  "recommended_next_action": "",
  "skip_flag": false,
  "skip_reason": "",
  "confidence": "High|Medium|Low"
}}

Lead: {json.dumps(lead)}
Research: {json.dumps(research)}
"""

def prompt_pipeline_manager(pipeline_state, agent_outputs, today):
    # Build a compact stage summary — don't pass full pipeline JSON
    stage_counts = {}
    for row in pipeline_state:
        s = str(row.get("current_stage","New"))
        stage_counts[s] = stage_counts.get(s, 0) + 1
    total = len(pipeline_state)
    return f"""
You are the Pipeline Manager Agent.
Move leads to the correct stage based on what agents just did.

Current pipeline: {total} leads across stages: {json.dumps(stage_counts)}
Agent batch results: {json.dumps(agent_outputs)}

STAGE ORDER: New→Researched→Qualified→Outreach Sent→Personalized→
Contacted→Engaged→At Risk→In Recovery→Escalated→Won→Lost→Skipped

For each lead in agent_outputs, set new_stage based on:
- Research completed → Researched
- Qualification done, not skipped → Qualified
- Qualification skip_flag=true → Skipped
- Outreach sent (not skipped) → Outreach Sent
- Personalization done → Personalized

Return ONLY valid JSON:
{{
  "pipeline_update": [
    {{
      "lead_id": "",
      "new_stage": "",
      "moved_by_agent": "",
      "timestamp": "{today}"
    }}
  ],
  "pipeline_velocity": "Fast|Normal|Slow|Stalled",
  "flagged_for_manager": []
}}
"""

def prompt_outreach(lead, research, qualification, product_context):
    return f"""
You are the Outreach Agent for a company selling: {product_context}

Write a first-touch cold email for this lead.

SUBJECT LINE: max 8 words, specific, no "Quick question" or "Following up"
BODY: max 120 words — count strictly
- Line 1: reference something specific about their company/role. NEVER start with I or We
- Lines 2-3: exactly ONE pain point — their pain, not our features
- Lines 4-5: what changes for THEM — outcome not feature
- Line 6: one small specific CTA answerable in one sentence
- Sign: [YOUR NAME], [YOUR TITLE]

TONE: Hot=direct peer-to-peer, Warm=curious helpful, Cold=educational soft

BANNED WORDS — if any appear rewrite:
synergy leverage cutting-edge innovative revolutionary excited thrilled
hoping just-wanted-to circle-back touch-base game-changer world-class
seamlessly robust scalable end-to-end holistic empower

RULES:
- Never mention features — only outcomes
- Never use company name more than once
- If skip_flag=true or email is empty — return empty email_body and note why

Return ONLY valid JSON:
{{
  "lead_id": "{lead.get('lead_id','')}",
  "subject_line": "",
  "email_body": "",
  "tone_used": "Direct|Curious|Educational",
  "primary_pain_addressed": "",
  "outcome_promised": "",
  "cta": "",
  "word_count": 0,
  "skipped_reason": ""
}}

Lead: {json.dumps(lead)}
Research: {json.dumps(research)}
Qualification: {json.dumps(qualification)}
"""

def prompt_personalization(lead, research, qualification,
                            outreach_email, mode, days_since_contact, product_context):
    return f"""
You are the Personalization Agent for a company selling: {product_context}
Mode: {mode}

MODE=refinement:
Review the outreach email. Make surgical edits only.
Look for: templated phrases, generic lines, missed research opportunities,
tone mismatch, subject line that could be sharper.
If already excellent — return unchanged and say why.
Never rewrite entirely — edit only what needs fixing.

MODE=follow-up:
Write the next message. Days since first contact: {days_since_contact}
- NEVER say "just following up" or "checking in"
- Add NEW value — new angle, insight, or question
- Day 3-5: one new relevant piece of info
- Day 8-10: completely different angle
- Day 14+: warm breakup email, leave door open
- Never make follow-up longer than original
- Never guilt trip for no response

RULES:
- Never invent information about the lead
- Every message must have a reason to exist beyond "we haven't heard from you"
- If lead has no email — return skipped_reason explaining why

Return ONLY valid JSON:
{{
  "lead_id": "{lead.get('lead_id','')}",
  "mode": "{mode}",
  "follow_up_number": 0,
  "refined_email": "",
  "subject_line": "",
  "changes_made": ["specific change and why"],
  "new_angle_used": "",
  "word_count": 0,
  "ready_to_send": true,
  "skipped_reason": ""
}}

Lead: {json.dumps(lead)}
Research: {json.dumps(research)}
Outreach email: {json.dumps(outreach_email)}
"""

def prompt_monitoring(lead, today, product_context):
    return f"""
You are the Monitoring Agent tracking leads for: {product_context}

Watch this lead for positive and negative signals.
OBSERVE AND CLASSIFY ONLY — do not recommend actions.

POSITIVE: reply received, meeting booked, document requested,
referral made, pricing question asked

NEGATIVE:
- No reply after: Hot=5d flag/8d critical, Warm=10d/15d, Cold=14d/21d
- Stall language: "not right now" "maybe later" "send info" "budget frozen"
- Competitor mentioned by name
- Wrong stakeholder
- Meeting cancelled twice or more

STATUS: On Track / At Risk / Critical / Won / Lost

RULES:
- Do not recommend actions — only classify signals
- Every signal must trace to actual data, not assumption
- Mark At Risk conservatively — earlier is better
- If no outreach sent yet — status = On Track, no signals

Return ONLY valid JSON:
{{
  "lead_id": "{lead.get('lead_id','')}",
  "tier": "Hot|Warm|Cold",
  "days_since_last_contact": 0,
  "velocity": "Fast|Normal|Slow|Stalled",
  "positive_signals": [],
  "negative_signals": [],
  "pipeline_status": "On Track|At Risk|Critical|Won|Lost",
  "urgency_score": 0,
  "flag_for_recovery": false,
  "flag_for_escalation": false,
  "monitor_notes": "one line observation"
}}

Lead: {json.dumps(lead)}
Today: {today}
"""

def prompt_recovery(lead, monitor_output, previous_attempts, product_context):
    return f"""
You are the Recovery Agent for a company selling: {product_context}

Save this stalling deal.

DIAGNOSE specifically — "No response after 12 days and competitor mentioned"
not "lead seems uninterested"

STRATEGIES:
1. Change Angle — lead with different pain from research
2. Change Stakeholder — contact someone else at the company
3. Add Value — send useful insight before asking anything
4. Create Urgency — real reason to act now, never fake
5. Go Silent — pause 10 days then one strong message
6. Walk Away — graceful breakup, door open for future

PROGRESSION:
- Attempt 1: Change Angle or Add Value
- Attempt 2: Change Stakeholder or Create Urgency
- Attempt 3+: Walk Away

RECOVERY EMAIL RULES:
- Under 100 words
- NEVER reference that they haven't replied — start fresh
- New subject — completely different from all previous
- Pattern interrupt opening — unexpected or unasked question
- One CTA — smaller than previous ask, not larger
- Walk away: warm, no guilt, specific future invitation

BANNED: never use same strategy as previous attempt

Return ONLY valid JSON:
{{
  "lead_id": "{lead.get('lead_id','')}",
  "recovery_attempt_number": {previous_attempts + 1},
  "diagnosis": "",
  "recovery_strategy": "Change Angle|Change Stakeholder|Add Value|Create Urgency|Go Silent|Walk Away",
  "strategy_reasoning": "",
  "recovery_subject": "",
  "recovery_email": "",
  "alternative_contact_suggestion": "",
  "walk_away": false,
  "recovery_confidence_pct": 0,
  "if_no_response": ""
}}

Monitor output: {json.dumps(monitor_output)}
Lead: {json.dumps(lead)}
Previous attempts: {previous_attempts}
"""

def prompt_escalation(all_outputs, threshold_value, today):
    return f"""
You are the Escalation Agent.
Protect the human's time — escalate ONLY what genuinely needs human decision.
Every unnecessary escalation is a failure of your job.

ESCALATE when ALL true:
- Hot tier AND Critical status AND Recovery attempted AND confidence < 35%
OR any ONE alone:
- C-suite personally engaged (CEO CFO COO CTO) needing senior response
- Legal language: contract liability compliance indemnity SLA
- Procurement involved: RFP vendor-evaluation formal-tender
- Named competitor mentioned by lead AND Hot tier
- Deal value signal above threshold AND Critical status

DO NOT ESCALATE:
- Cold tier (ever)
- First outreach no response
- Recovery confidence above 60%
- Ambiguous but not urgent

FOR EACH ESCALATION:
- Specific reason with actual signal data
- Exact question human must answer
- Deadline based on urgency
- Fallback if human doesn't respond

Return ONLY valid JSON:
{{
  "escalations": [
    {{
      "lead_id": "",
      "escalation_trigger": "",
      "reason": "specific sentence with actual data",
      "decision_needed": "exact question",
      "deadline": "",
      "urgency": "Immediate|Today|This Week",
      "fallback_action": "real action not monitor further"
    }}
  ],
  "total_escalations": 0,
  "autonomous_leads": 0
}}

All outputs: {json.dumps(all_outputs[-15:])}
Today: {today}
"""

def prompt_marketing_intel(campaign_data, outreach_data, engagement_data, product_context):
    return f"""
You are the Marketing Intelligence Agent for: {product_context}

Find patterns in this campaign data. You are a pattern finder not a summariser.
Every insight must have specific evidence from THIS data.

ANALYSE:
- Which subject lines got replies vs silence
- Which pain points resonated by industry and role
- Which CTAs worked vs ignored
- Which industries/seniority levels are responding
- Tone performance by tier

BAD insight: "Personalisation increases reply rates"
GOOD insight: "Emails leading with cost reduction got 3x more replies 
than efficiency emails in the fintech segment"

If sample too small — say so explicitly.

Return ONLY valid JSON:
{{
  "sample_size": 0,
  "insights": [
    {{"finding": "", "evidence": "", "recommendation": "", "confidence": "High|Medium|Low"}}
  ],
  "best_subject_formula": "",
  "worst_performing_element": "",
  "pain_points_by_industry": {{}},
  "tone_recommendation_by_tier": {{"Hot":"","Warm":"","Cold":""}},
  "stop_doing_immediately": "",
  "next_batch_strategy": "",
  "data_limitations": ""
}}

Campaign: {json.dumps(campaign_data)}
Outreach: {json.dumps(outreach_data)}
Engagement: {json.dumps(engagement_data)}
"""

def prompt_reporting(pipeline_summary, key_outputs, marketing_output, today, product_context):
    return f"""
You are the Reporting Agent for a company selling: {product_context}

Write the daily manager report. Read in 2 minutes over coffee.
Tell them exactly what happened, what matters, what to do.

Pipeline health score 0-100 (On Track ratio, velocity, wins vs losses).
Pick 3 most important numbers with context.
List only Critical and At Risk leads needing attention.
List positive momentum leads.
List escalations awaiting decision.
List autonomous actions completed.
Top marketing insight and one change for tomorrow.
Tomorrow's plan.
Final sentence: one clear instruction for the manager.

RULES: under 350 words, no jargon, every claim has a number,
write like a chief of staff not a dashboard.

Return ONLY valid JSON:
{{
  "report_date": "{today}",
  "pipeline_health_score": 0,
  "health_explanation": "",
  "three_key_numbers": [
    {{"metric":"","value":"","context":""}}
  ],
  "needs_attention": [
    {{"lead_id":"","lead_name":"","risk_reason":"","action_taken":"","next_24h":""}}
  ],
  "positive_momentum": [
    {{"lead_id":"","lead_name":"","signal":""}}
  ],
  "escalations_awaiting": [],
  "autonomous_actions_completed": [],
  "optimization_intelligence": {{
    "top_insight":"","change_for_tomorrow":"","stop_doing":""
  }},
  "tomorrows_plan": {{
    "autonomous_actions":[],"human_decisions_needed":[]
  }},
  "focus_sentence": ""
}}

Pipeline: {json.dumps(pipeline_summary)}
Key outputs: {json.dumps(key_outputs)}
Marketing: {json.dumps(marketing_output)}
Today: {today}
"""

# =============================================================
# ── AGENT RUNNER FUNCTIONS ────────────────────────────────────
# Each: set status → call LLM → update df → set status done
# Max retries handled inside call_llm — these never infinite loop
# =============================================================

def run_manager(df):
    set_agent("Manager", "running")
    add_reasoning("Manager reading pipeline and building execution plan...")
    # Keep payload tiny — apifreellm has small context window
    new_count      = int((df["current_stage"]=="New").sum())
    contacted_count= int(df["current_stage"].isin(["Contacted","Engaged","Personalized","Outreach Sent"]).sum())
    at_risk_count  = int(df["pipeline_status"].isin(["At Risk","Critical"]).sum())
    lead_ids       = df["lead_id"].astype(str).tolist()
    result = call_llm(
        prompt_manager(new_count, contacted_count, at_risk_count,
                       lead_ids, get_product_context(), len(df)),
        agent_name="Manager"
    )
    if result:
        for line in result.get("reasoning_trail", []):
            add_reasoning(line)
        set_agent("Manager", "done", leads_done=len(df))
        log_flow("Manager", "Research", "all")
    else:
        # Manager failed — use sensible defaults, don't block
        set_agent("Manager", "error")
        add_reasoning(f"Manager failed — running default plan: Research+Qualify all {new_count} new leads.")
    return result


def run_research(df, lead_row):
    lead_id = str(lead_row.get("lead_id",""))
    set_agent("Research", "running")
    # Only pass the 6 input fields — don't send 37 columns of empty data
    slim_lead = {k: lead_row.get(k,"") for k in
                 ["lead_id","full_name","company_name","role_title","email","phone"]}
    result = call_llm(
        prompt_research(slim_lead, get_product_context(),
                        datetime.now().strftime("%Y-%m-%d %H:%M")),
        agent_name="Research", lead_id=lead_id
    )
    if result:
        df = update_lead(df, lead_id, {
            "industry":             result.get("industry",""),
            "company_size":         result.get("company_size",""),
            "business_model":       result.get("business_model",""),
            "company_summary":      result.get("company_summary",""),
            "growth_signals":       result.get("growth_signals",""),
            "pain_point_1":         result.get("pain_point_1",""),
            "tech_stack_inferred":  result.get("tech_stack_inferred",""),
            "conversation_hook":    result.get("conversation_hook",""),
            "best_approach_angle":  result.get("best_approach_angle",""),
            "research_completed_at":result.get("research_completed_at",""),
            "current_stage":        "Researched",
            "last_agent_run":       "Research",
        })
        set_agent("Research", "done", leads_done=1)
        log_flow("Research", "Qualification", lead_id)
        add_reasoning(f"Research done for {lead_row.get('full_name',lead_id)}.")
    else:
        set_agent("Research", "error")
    return result, df


def run_qualification(df, lead_row, research):
    lead_id = str(lead_row.get("lead_id",""))
    set_agent("Qualification", "running")
    # Use slim version — only pass what qualification needs
    slim_lead = {k: lead_row.get(k,"") for k in
                 ["lead_id","full_name","company_name","role_title","email","phone"]}
    # Slim research — only the fields that matter for scoring
    slim_research = {k: research.get(k,"") for k in
                     ["industry","company_size","business_model",
                      "pain_point_1","growth_signals","best_approach_angle"]}
    result = call_llm(
        prompt_qualification(slim_lead, slim_research, get_product_context()),
        agent_name="Qualification", lead_id=lead_id
    )
    if result:
        new_stage = "Skipped" if result.get("skip_flag") else "Qualified"
        df = update_lead(df, lead_id, {
            "qualification_score": result.get("qualification_score",""),
            "qualification_tier":  result.get("qualification_tier",""),
            "tier_reasoning":      result.get("tier_reasoning",""),
            "skip_flag":           str(result.get("skip_flag",False)),
            "skip_reason":         result.get("skip_reason",""),
            "current_stage":       new_stage,
            "last_agent_run":      "Qualification",
        })
        tier  = result.get("qualification_tier","")
        score = result.get("qualification_score",0)
        set_agent("Qualification", "done", leads_done=1)
        log_flow("Qualification", "Pipeline Manager", lead_id)
        add_reasoning(
            f"{lead_row.get('full_name',lead_id)}: {score}/100 — {tier}."
            + (f" Skipping: {result.get('skip_reason','')}" if result.get("skip_flag") else "")
        )
    else:
        set_agent("Qualification", "error")
    return result, df


def run_pipeline_manager(df, agent_outputs):
    set_agent("Pipeline Manager", "running")
    # Pass compact stage summary not full df
    stage_summary = df[["lead_id","current_stage","pipeline_status"]].to_dict(orient="records")
    result = call_llm(
        prompt_pipeline_manager(
            stage_summary, agent_outputs, str(date.today())
        ),
        agent_name="Pipeline Manager"
    )
    if result:
        for upd in result.get("pipeline_update", []):
            lid       = upd.get("lead_id","")
            new_stage = upd.get("new_stage","")
            if lid and new_stage:
                mask = df["lead_id"].astype(str) == str(lid)
                if mask.any():
                    old_hist = str(df.loc[mask,"stage_history"].values[0])
                    new_hist = f"{old_hist}, {new_stage}"
                    df = update_lead(df, lid, {
                        "current_stage": new_stage,
                        "stage_history": new_hist,
                        "last_agent_run":"Pipeline Manager",
                    })
        vel = result.get("pipeline_metrics",{}).get("pipeline_velocity","—")
        set_agent("Pipeline Manager", "done", leads_done=len(df))
        log_flow("Pipeline Manager", "Outreach", "all")
        add_reasoning(f"Pipeline updated. Velocity: {vel}.")
    else:
        set_agent("Pipeline Manager", "error")
    return result, df


def run_outreach(df, lead_row, research, qualification):
    lead_id = str(lead_row.get("lead_id",""))
    set_agent("Outreach", "running")
    email_val = str(lead_row.get("email","")).strip()

    if not email_val or "@" not in email_val:
        set_agent("Outreach", "done", leads_done=1)
        add_reasoning(f"Skipping outreach for {lead_row.get('full_name',lead_id)} — no valid email.")
        return {"skipped_reason":"no valid email","subject_line":"","email_body":""}, df

    slim_lead = {k: lead_row.get(k,"") for k in
                 ["lead_id","full_name","company_name","role_title","email"]}
    slim_research = {k: research.get(k,"") for k in
                     ["industry","company_size","pain_point_1",
                      "conversation_hook","best_approach_angle","growth_signals"]}
    slim_qual = {k: qualification.get(k,"") for k in
                 ["qualification_tier","qualification_score","tier_reasoning"]}
    result = call_llm(
        prompt_outreach(slim_lead, slim_research, slim_qual, get_product_context()),
        agent_name="Outreach", lead_id=lead_id
    )
    if result and result.get("email_body"):
        df = update_lead(df, lead_id, {
            "outreach_subject": result.get("subject_line",""),
            "outreach_sent_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "follow_up_number": 0,
            "current_stage":    "Outreach Sent",
            "last_agent_run":   "Outreach",
        })
        set_agent("Outreach", "done", leads_done=1)
        log_flow("Outreach", "Personalization", lead_id)
        add_reasoning(
            f"Outreach written for {lead_row.get('full_name',lead_id)}: "
            f"'{result.get('subject_line','')}'"
        )
    elif result:
        set_agent("Outreach", "done", leads_done=1)
        add_reasoning(f"Outreach skipped for {lead_id}: {result.get('skipped_reason','')}")
    else:
        set_agent("Outreach", "error")
    return result, df


def run_personalization(df, lead_row, research, qualification,
                         outreach_result, mode, days_since_contact):
    lead_id = str(lead_row.get("lead_id",""))
    set_agent("Personalization", "running")

    if not str(lead_row.get("email","")).strip() or "@" not in str(lead_row.get("email","")):
        set_agent("Personalization", "done", leads_done=1)
        return {"skipped_reason":"no valid email"}, df

    result = call_llm(
        prompt_personalization(
            lead_row, research, qualification, outreach_result,
            mode, days_since_contact, get_product_context()
        ),
        agent_name="Personalization", lead_id=lead_id
    )
    if result:
        fn = int(result.get("follow_up_number", 0))
        df = update_lead(df, lead_id, {
            "follow_up_number": fn,
            "outreach_subject":  result.get("subject_line",""),
            "current_stage":     "Personalized",
            "last_agent_run":    "Personalization",
        })
        set_agent("Personalization", "done", leads_done=1)
        log_flow("Personalization", "Monitoring", lead_id)
        add_reasoning(
            f"Personalization {'refined' if mode=='refinement' else f'follow-up #{fn}'} "
            f"for {lead_row.get('full_name',lead_id)}."
        )
    else:
        set_agent("Personalization", "error")
    return result, df


def run_monitoring(df, lead_row):
    lead_id = str(lead_row.get("lead_id",""))
    set_agent("Monitoring", "running")
    slim = {k: lead_row.get(k,"") for k in [
        "lead_id","full_name","company_name","role_title",
        "qualification_tier","current_stage","pipeline_status",
        "outreach_sent_at","follow_up_number","days_since_contact",
        "positive_signals","negative_signals","urgency_score"
    ]}
    result = call_llm(
        prompt_monitoring(slim, str(date.today()), get_product_context()),
        agent_name="Monitoring", lead_id=lead_id
    )
    if result:
        status = result.get("pipeline_status","")
        df = update_lead(df, lead_id, {
            "pipeline_status":    status,
            "urgency_score":      result.get("urgency_score",""),
            "positive_signals":   ", ".join(result.get("positive_signals",[])),
            "negative_signals":   ", ".join(result.get("negative_signals",[])),
            "days_since_contact": result.get("days_since_last_contact",""),
            "current_stage":      "At Risk" if status in ("At Risk","Critical") else lead_row.get("current_stage",""),
            "last_agent_run":     "Monitoring",
        })
        set_agent("Monitoring", "done", leads_done=1)
        log_flow("Monitoring", "Recovery", lead_id)
        add_reasoning(
            f"{lead_row.get('full_name',lead_id)}: {status}. "
            f"Urgency {result.get('urgency_score',0)}/10."
        )
    else:
        set_agent("Monitoring", "error")
    return result, df


def run_recovery(df, lead_row, monitor_output):
    lead_id  = str(lead_row.get("lead_id",""))
    prev_att = int(str(lead_row.get("recovery_attempts",0) or 0))
    set_agent("Recovery", "running")
    slim = {k: lead_row.get(k,"") for k in [
        "lead_id","full_name","company_name","role_title",
        "qualification_tier","outreach_subject","pain_point_1",
        "recovery_attempts","recovery_strategy","pipeline_status"
    ]}
    result = call_llm(
        prompt_recovery(slim, monitor_output, prev_att, get_product_context()),
        agent_name="Recovery", lead_id=lead_id
    )
    if result:
        df = update_lead(df, lead_id, {
            "recovery_attempts":       result.get("recovery_attempt_number", prev_att+1),
            "recovery_strategy":       result.get("recovery_strategy",""),
            "recovery_confidence_pct": result.get("recovery_confidence_pct",""),
            "walk_away_flag":          str(result.get("walk_away",False)),
            "current_stage":           "In Recovery",
            "last_agent_run":          "Recovery",
        })
        set_agent("Recovery", "done", leads_done=1)
        log_flow("Recovery", "Escalation", lead_id)
        add_reasoning(
            f"Recovery for {lead_row.get('full_name',lead_id)}: "
            f"{result.get('recovery_strategy','')} — "
            f"{result.get('recovery_confidence_pct',0)}% confidence."
        )
    else:
        set_agent("Recovery", "error")
    return result, df


def run_escalation(df, all_outputs):
    set_agent("Escalation", "running")
    # Only pass the summary fields needed for escalation decisions
    esc_summary = []
    for o in all_outputs[-20:]:  # last 20 only
        out = o.get("output", {})
        if isinstance(out, dict):
            esc_summary.append({
                "agent":   o.get("agent",""),
                "lead_id": o.get("lead_id",""),
                "tier":    out.get("qualification_tier",""),
                "status":  out.get("pipeline_status",""),
                "urgency": out.get("urgency_score",""),
                "confidence": out.get("recovery_confidence_pct",""),
                "recovery_attempted": bool(out.get("recovery_strategy","")),
            })
    result = call_llm(
        prompt_escalation(esc_summary, "high-value", str(date.today())),
        agent_name="Escalation"
    )
    if result:
        for esc in result.get("escalations", []):
            lid = esc.get("lead_id","")
            if lid:
                df = update_lead(df, lid, {
                    "escalation_flag":    "true",
                    "escalation_urgency": esc.get("urgency",""),
                    "escalation_reason":  esc.get("reason",""),
                    "current_stage":      "Escalated",
                    "last_agent_run":     "Escalation",
                })
        total = result.get("total_escalations", 0)
        set_agent("Escalation", "done", leads_done=len(df))
        log_flow("Escalation", "Marketing Intelligence", "all")
        add_reasoning(f"Escalation done — {total} deals flagged for human review.")
    else:
        set_agent("Escalation", "error")
    return result, df


def run_marketing_intel(df):
    set_agent("Marketing Intelligence", "running")
    # Only include leads that have outreach data
    sent = df[df["outreach_subject"].astype(str).str.strip() != ""]
    out_data = sent[["lead_id","industry","qualification_tier",
                     "outreach_subject","pipeline_status"]].to_dict(orient="records")
    # Compact campaign summary
    campaign = {
        "total":    len(df),
        "hot":      int((df["qualification_tier"]=="Hot").sum()),
        "warm":     int((df["qualification_tier"]=="Warm").sum()),
        "cold":     int((df["qualification_tier"]=="Cold").sum()),
        "on_track": int((df["pipeline_status"]=="On Track").sum()),
        "at_risk":  int((df["pipeline_status"].isin(["At Risk","Critical"])).sum()),
        "outreach_sent": len(sent),
    }
    result = call_llm(
        prompt_marketing_intel(
            campaign, out_data[:10],  # max 10 leads
            [], get_product_context()
        ),
        agent_name="Marketing Intelligence"
    )
    if result:
        st.session_state["last_marketing"] = result
        set_agent("Marketing Intelligence", "done", leads_done=len(df))
        log_flow("Marketing Intelligence", "Reporting", "all")
        add_reasoning(
            f"Marketing Intel: {len(result.get('insights',[]))} patterns found "
            f"across {result.get('sample_size',0)} leads."
        )
    else:
        set_agent("Marketing Intelligence", "error")
    return result


def run_reporting(df, all_outputs, marketing_output):
    set_agent("Reporting", "running")
    # Build compact pipeline summary for reporting
    pipeline_summary = {
        "total":    len(df),
        "by_tier":  df["qualification_tier"].value_counts().to_dict(),
        "by_stage": df["current_stage"].value_counts().to_dict(),
        "by_status":df["pipeline_status"].value_counts().to_dict(),
        "escalated":int((df["escalation_flag"]=="true").sum()),
        "emails_sent": int((df["outreach_subject"].astype(str).str.strip()!="").sum()),
        "recovery_attempts": int(df["recovery_attempts"].astype(str).apply(
            lambda x: int(x) if x.isdigit() else 0).sum()),
    }
    # Key agent outputs only
    key_outputs = []
    for o in all_outputs:
        out = o.get("output",{})
        if isinstance(out,dict) and o.get("agent") in (
            "Manager","Escalation","Marketing Intelligence"):
            key_outputs.append({"agent":o["agent"],"summary":str(out)[:200]})
    result = call_llm(
        prompt_reporting(pipeline_summary, key_outputs, marketing_output,
                         str(date.today()), get_product_context()),
        agent_name="Reporting"
    )
    if result:
        st.session_state["last_report"] = result
        rpath = os.path.join(REPORTS_DIR, f"report_{date.today()}.json")
        try:
            with open(rpath,"w") as f:
                json.dump(result, f, indent=2)
        except Exception:
            pass
        set_agent("Reporting", "done", leads_done=len(df))
        add_reasoning(
            f"Report done. Health: {result.get('pipeline_health_score',0)}/100. "
            f"{result.get('focus_sentence','')}"
        )
    else:
        set_agent("Reporting", "error")
    return result

# =============================================================
# ── MAIN ORCHESTRATOR ─────────────────────────────────────────
# =============================================================

def run_full_engine(df: pd.DataFrame) -> pd.DataFrame:
    """
    Runs all 11 agents in Manager-decided order.
    Sequential execution, parallel visuals.
    Hard-bounded — no infinite loops.
    CSV updated after every agent.
    """
    st.session_state["engine_running"] = True
    st.session_state["run_complete"]   = False
    st.session_state["run_errors"]     = []
    st.session_state["manager_reasoning"] = []
    st.session_state["data_flow_log"]     = []

    for a in st.session_state["agent_statuses"]:
        set_agent(a, "idle")
    for a in st.session_state["agent_counts"]:
        st.session_state["agent_counts"][a] = 0

    all_outputs   = []
    research_cache = {}
    qual_cache     = {}
    outreach_cache = {}
    monitor_cache  = {}

    product = get_product_context()
    add_reasoning(f"Engine starting. Product: {product}. {len(df)} leads loaded.")

    # ── MANAGER ───────────────────────────────────────────────
    with st.status("🧠 Manager Agent — reading pipeline, building plan...", expanded=False) as _s:
        manager_result = run_manager(df)
        if manager_result:
            all_outputs.append({"agent":"Manager","output":manager_result})
            _s.update(label="✅ Manager Agent — execution plan ready", state="complete")
        else:
            _s.update(label="⚠️ Manager Agent — using default plan", state="error")

    # ── NEW LEADS PIPELINE ────────────────────────────────────
    new_leads = df[df["current_stage"]=="New"].to_dict(orient="records")

    if new_leads:
        add_reasoning(f"Processing {len(new_leads)} new leads: Research → Qualification (simulated parallel).")

        with st.status(f"🔍 Research + 📊 Qualification — {len(new_leads)} leads...", expanded=False) as _s:
            for idx, lead_row in enumerate(new_leads):
                lid = str(lead_row.get("lead_id",""))
                name = lead_row.get("full_name", lid)
                _s.update(label=f"🔍 Researching {name} ({idx+1}/{len(new_leads)})...")

                # Research
                res, df = run_research(df, lead_row)
                if res:
                    research_cache[lid] = res
                    all_outputs.append({"agent":"Research","lead_id":lid,"output":res})
                else:
                    add_reasoning(f"Research failed for {lid} — skipping qualification.")
                    continue

                # Qualification
                _s.update(label=f"📊 Qualifying {name} ({idx+1}/{len(new_leads)})...")
                qual, df = run_qualification(df, lead_row, res)
                if qual:
                    qual_cache[lid] = qual
                    all_outputs.append({"agent":"Qualification","lead_id":lid,"output":qual})
                else:
                    add_reasoning(f"Qualification failed for {lid} — using defaults.")
                    qual_cache[lid] = {"qualification_tier":"Cold","qualification_score":0,"skip_flag":False}

            _s.update(label=f"✅ Research + Qualification done — {len(new_leads)} leads processed", state="complete")

        # Pipeline Manager after Research + Qualification batch
        # Use only the outputs generated in THIS batch, not a slice that could be wrong
        # Build slim pipeline update summary for Pipeline Manager
        rq_summary = []
        for o in all_outputs:
            if o.get("agent") in ("Research","Qualification"):
                out = o.get("output",{})
                rq_summary.append({
                    "agent": o["agent"],
                    "lead_id": o.get("lead_id",""),
                    "tier": out.get("qualification_tier",""),
                    "score": out.get("qualification_score",""),
                    "skip": out.get("skip_flag",False),
                    "stage": "Researched" if o["agent"]=="Research" else "Qualified",
                })
        pm1, df = run_pipeline_manager(df, rq_summary)
        if pm1:
            all_outputs.append({"agent":"Pipeline Manager","output":pm1})

        # Outreach for non-skipped leads — read from LIVE df (post-qualification)
        # new_leads is stale; df now has skip_flag set by Qualification
        new_lead_ids = [str(r.get("lead_id","")) for r in new_leads]
        eligible_rows = df[
            (df["lead_id"].astype(str).isin(new_lead_ids)) &
            (df["skip_flag"].astype(str) != "true") &
            (df["email"].astype(str).str.contains("@", na=False))
        ]
        eligible = eligible_rows.to_dict(orient="records")

        with st.status(f"✉️ Outreach + 🎯 Personalization — {len(eligible)} leads...", expanded=False) as _s:
            for idx, lead_row in enumerate(eligible):
                lid = str(lead_row.get("lead_id",""))
                fresh = df[df["lead_id"].astype(str)==lid].to_dict(orient="records")
                lead_row = fresh[0] if fresh else lead_row
                name = lead_row.get("full_name", lid)

                if str(lead_row.get("skip_flag","")) == "true":
                    continue

                res  = research_cache.get(lid,{})
                qual = qual_cache.get(lid,{})

                _s.update(label=f"✉️ Writing outreach for {name} ({idx+1}/{len(eligible)})...")
                out, df = run_outreach(df, lead_row, res, qual)
                if out:
                    outreach_cache[lid] = out
                    all_outputs.append({"agent":"Outreach","lead_id":lid,"output":out})

                # Personalization — refine immediately after outreach
                if out and out.get("email_body"):
                    fresh = df[df["lead_id"].astype(str)==lid].to_dict(orient="records")
                    lead_row = fresh[0] if fresh else lead_row
                    _s.update(label=f"🎯 Personalizing for {name} ({idx+1}/{len(eligible)})...")
                    pers, df = run_personalization(
                        df, lead_row, res, qual, out,
                        mode="refinement", days_since_contact=0
                    )
                    if pers:
                        all_outputs.append({"agent":"Personalization","lead_id":lid,"output":pers})

            _s.update(label=f"✅ Outreach + Personalization done — {len(eligible)} leads", state="complete")

        # Pipeline Manager after Outreach + Personalization
        op_summary = []
        for o in all_outputs:
            if o.get("agent") in ("Outreach","Personalization"):
                out = o.get("output",{})
                op_summary.append({
                    "agent": o["agent"],
                    "lead_id": o.get("lead_id",""),
                    "subject": out.get("subject_line",""),
                    "stage": "Outreach Sent" if o["agent"]=="Outreach" else "Personalized",
                    "skipped": bool(out.get("skipped_reason","")),
                })
        pm2, df = run_pipeline_manager(df, op_summary)
        if pm2:
            all_outputs.append({"agent":"Pipeline Manager 2","output":pm2})

    # ── EXISTING / CONTACTED LEADS ────────────────────────────
    contacted = df[df["current_stage"].isin([
        "Contacted","Engaged","Personalized","Outreach Sent"
    ])].to_dict(orient="records")

    if contacted:
        add_reasoning(f"Monitoring {len(contacted)} active deals for signals.")
        with st.status(f"👁️ Monitoring — {len(contacted)} active deals...", expanded=False) as _s:
            for idx, lead_row in enumerate(contacted):
                lid  = str(lead_row.get("lead_id",""))
                name = lead_row.get("full_name", lid)
                _s.update(label=f"👁️ Monitoring {name} ({idx+1}/{len(contacted)})...")
                mon, df = run_monitoring(df, lead_row)
                if mon:
                    monitor_cache[lid] = mon
                    all_outputs.append({"agent":"Monitoring","lead_id":lid,"output":mon})
            _s.update(label=f"✅ Monitoring done — {len(contacted)} deals checked", state="complete")

        # Recovery for flagged leads only
        recovery_leads = [
            df[df["lead_id"].astype(str)==lid].to_dict(orient="records")[0]
            for lid, mon in monitor_cache.items()
            if mon.get("flag_for_recovery")
            and len(df[df["lead_id"].astype(str)==lid]) > 0
        ]

        if recovery_leads:
            add_reasoning(f"{len(recovery_leads)} leads flagged for recovery.")
            with st.status(f"🚨 Recovery — {len(recovery_leads)} at-risk deals...", expanded=False) as _s:
                for idx, lead_row in enumerate(recovery_leads):
                    lid     = str(lead_row.get("lead_id",""))
                    name    = lead_row.get("full_name", lid)
                    mon_out = monitor_cache.get(lid,{})
                    _s.update(label=f"🚨 Recovery play for {name} ({idx+1}/{len(recovery_leads)})...")
                    rec, df = run_recovery(df, lead_row, mon_out)
                    if rec:
                        all_outputs.append({"agent":"Recovery","lead_id":lid,"output":rec})
                _s.update(label=f"✅ Recovery done — {len(recovery_leads)} plays generated", state="complete")
        else:
            add_reasoning("No leads flagged for recovery — all active deals on track.")

    # ── AT RISK leads not already in recovery ─────────────────
    at_risk = df[
        (df["pipeline_status"].isin(["At Risk","Critical"])) &
        (~df["current_stage"].isin(["In Recovery","Escalated","Won","Lost"]))
    ].to_dict(orient="records")

    for lead_row in at_risk:
        lid = str(lead_row.get("lead_id",""))
        if lid not in monitor_cache:
            mon, df = run_monitoring(df, lead_row)
            if mon:
                monitor_cache[lid] = mon
                all_outputs.append({"agent":"Monitoring","lead_id":lid,"output":mon})
            if mon and mon.get("flag_for_recovery"):
                rec, df = run_recovery(df, lead_row, mon)
                if rec:
                    all_outputs.append({"agent":"Recovery","lead_id":lid,"output":rec})

    # ── ESCALATION ────────────────────────────────────────────
    with st.status("⚠️ Escalation Agent — reviewing all outputs...", expanded=False) as _s:
        esc, df = run_escalation(df, all_outputs)
        if esc:
            all_outputs.append({"agent":"Escalation","output":esc})
            n_esc = esc.get("total_escalations", 0)
            _s.update(label=f"✅ Escalation done — {n_esc} deals flagged", state="complete")
        else:
            _s.update(label="⚠️ Escalation — no output", state="error")

    # ── MARKETING INTELLIGENCE ────────────────────────────────
    with st.status("📈 Marketing Intelligence — finding patterns...", expanded=False) as _s:
        mkt = run_marketing_intel(df)
        if mkt:
            all_outputs.append({"agent":"Marketing Intelligence","output":mkt})
            _s.update(label=f"✅ Marketing Intel done — {len(mkt.get('insights',[]))} insights", state="complete")
        else:
            _s.update(label="⚠️ Marketing Intel — no output", state="error")

    # ── REPORTING ─────────────────────────────────────────────
    with st.status("📄 Reporting Agent — writing daily report...", expanded=False) as _s:
        rep = run_reporting(df, all_outputs, mkt or {})
        if rep:
            all_outputs.append({"agent":"Reporting","output":rep})
            score = rep.get("pipeline_health_score", 0)
            _s.update(label=f"✅ Report done — Pipeline Health: {score}/100", state="complete")
        else:
            _s.update(label="⚠️ Reporting — no output", state="error")

    # ── SEND REAL EMAILS ──────────────────────────────────────
    emails_sent = 0
    email_errors = []
    sendable = {lid: out for lid, out in outreach_cache.items()
                if out.get("subject_line") and out.get("email_body")}
    email_status_label = f"📧 Sending {len(sendable)} outreach emails via Outlook..."
    with st.status(email_status_label, expanded=False) as _s:
        for lid, out in outreach_cache.items():
            subj = out.get("subject_line","")
            body = out.get("email_body","")
            if not subj or not body:
                continue
            fresh = df[df["lead_id"].astype(str)==lid].to_dict(orient="records")
            if not fresh:
                continue
            row   = fresh[0]
            to_email = str(row.get("email",""))
            if not to_email or "@" not in to_email:
                continue
            _s.update(label=f"📧 Sending to {row.get('full_name', lid)}...")
            success, msg = send_email(to_email, subj, body)
            if success:
                emails_sent += 1
            else:
                email_errors.append(f"{row.get('full_name',lid)}: {msg}")

    if emails_sent or email_errors:
        add_reasoning(
            f"Email sending: {emails_sent} sent"
            + (f", {len(email_errors)} failed" if email_errors else "") + "."
        )
        for err in email_errors:
            log_error("Email", "", err)
    try:
        _s.update(label=f"✅ Emails: {emails_sent} sent" +
                  (f", {len(email_errors)} failed" if email_errors else ""),
                  state="complete" if not email_errors else "error")
    except Exception:
        pass

    # ── FINAL SAVE ────────────────────────────────────────────
    save_pipeline(df)
    st.session_state["pipeline_df"]    = df
    st.session_state["engine_running"] = False
    st.session_state["run_complete"]   = True
    add_reasoning("All agents complete. Pipeline saved. Report ready.")
    return df

# =============================================================
# ── GLOBAL STYLES ─────────────────────────────────────────────
# =============================================================

GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Syne:wght@400;700;800&display=swap');

* { box-sizing: border-box; }
.stApp { background: #07070f; color: #c8c8d8; font-family: 'Syne', sans-serif; }
.stApp h1,h2,h3,h4 { font-family: 'Syne', sans-serif; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    background: #0d0d1a; border-bottom: 1px solid #1a1a2e; gap: 4px;
}
.stTabs [data-baseweb="tab"] {
    color: #555 !important; font-weight: 700; font-size: 13px;
    padding: 10px 20px; border-radius: 6px 6px 0 0;
}
.stTabs [aria-selected="true"] {
    color: #fff !important; background: #1a1a2e !important;
}

/* Metrics */
div[data-testid="metric-container"] {
    background: #0d0d1a; border: 1px solid #1a1a2e;
    border-radius: 8px; padding: 12px 16px;
}
div[data-testid="metric-container"] label { color: #666 !important; font-size: 11px; }
div[data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: #fff; font-size: 22px; font-weight: 800;
}

/* Buttons */
.stButton > button {
    background: #0d0d1a; border: 1px solid #2a2a4a;
    color: #aaa; font-weight: 700; border-radius: 6px;
    transition: all 0.2s;
}
.stButton > button:hover {
    background: #1a1a3a; border-color: #5a5aaa; color: #fff;
}
.stButton > button[kind="primary"] {
    background: #0a2a0a; border-color: #2a6a2a; color: #aaffaa;
}
.stButton > button[kind="primary"]:hover {
    background: #0a3a0a; border-color: #4aaa4a;
}

/* Upload */
.stFileUploader { background: #0d0d1a; border-radius: 8px; padding: 4px; }

/* Expander */
.streamlit-expanderHeader {
    background: #0d0d1a !important; border: 1px solid #1a1a2e !important;
    border-radius: 6px !important; color: #aaa !important;
}

/* Sidebar */
[data-testid="stSidebar"] { background: #05050d !important; }
[data-testid="stSidebar"] .stMarkdown p { color: #888 !important; }

/* Divider */
hr { border-color: #1a1a2e !important; }

/* Code */
code { background: #0d0d1a !important; color: #7a9fff !important;
       font-family: 'JetBrains Mono', monospace !important; }

/* Containers with border */
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: #1a1a2e !important; border-radius: 8px !important;
    background: #0d0d1a !important;
}

/* Input fields */
.stTextInput input, .stTextArea textarea {
    background: #0d0d1a !important; border-color: #2a2a4a !important;
    color: #ddd !important;
}
.stSelectbox select { background: #0d0d1a !important; color: #ddd !important; }

/* Status boxes */
.stStatus { border-left: 2px solid #2a2a6a !important; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #07070f; }
::-webkit-scrollbar-thumb { background: #2a2a4a; border-radius: 3px; }

/* Force dark on dataframes */
.stDataFrame { background: #0d0d1a !important; }
.stDataFrame thead th { background: #1a1a2e !important; color: #aaa !important; }
.stDataFrame tbody td { background: #0d0d1a !important; color: #ccc !important; }

/* Force dark on alerts */
.stAlert { background: #0d0d1a !important; }
.stSuccess { background: #001a00 !important; border-color: #224422 !important; }
.stWarning { background: #1a1500 !important; border-color: #443300 !important; }
.stError   { background: #1a0000 !important; border-color: #441111 !important; }
.stInfo    { background: #001020 !important; border-color: #112244 !important; }

/* Status containers */
div[data-testid="stStatusContainer"] {
    background: #0d0d1a !important;
    border: 1px solid #1a1a2e !important;
    border-radius: 8px !important;
}

/* Spinner */
.stSpinner > div { border-top-color: #6a9fff !important; }

/* Slider */
.stSlider [data-baseweb="slider"] { background: #1a1a2e !important; }

/* Multiselect */
.stMultiSelect [data-baseweb="select"] {
    background: #0d0d1a !important; border-color: #2a2a4a !important;
}
.stMultiSelect [data-baseweb="tag"] {
    background: #1a1a3a !important; color: #aaa !important;
}

/* File uploader drop zone */
[data-testid="stFileUploader"] section {
    background: #0d0d1a !important;
    border-color: #2a2a4a !important;
}
[data-testid="stFileUploader"] section:hover {
    border-color: #6a6aaa !important;
    background: #0d0d2a !important;
}

/* Tooltip / popover */
[data-baseweb="popover"] { background: #1a1a2e !important; }

/* Remove white flash on page load */
html { background: #07070f !important; }

/* Flowchart animations */
@keyframes pulse-yellow { 0%,100%{box-shadow:0 0 0 0 rgba(255,200,0,0)}
    50%{box-shadow:0 0 12px 3px rgba(255,200,0,0.4)} }
@keyframes pulse-green  { 0%,100%{box-shadow:0 0 0 0 rgba(0,200,0,0)}
    50%{box-shadow:0 0 12px 3px rgba(0,200,0,0.2)} }
@keyframes flow-right { 0%{left:-10%} 100%{left:110%} }
@keyframes flow-down  { 0%{top:-10%}  100%{top:110%}  }
@keyframes fade-in { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
</style>
"""

# =============================================================
# ── SIDEBAR ───────────────────────────────────────────────────
# =============================================================

def render_sidebar(df):
    st.sidebar.markdown(GLOBAL_CSS, unsafe_allow_html=True)
    st.sidebar.markdown("""
    <style>
    [data-testid="stSidebar"] * { color: #c8c8d8 !important; }
    .sb-agent { display:flex;align-items:center;gap:8px;padding:5px 10px;
                margin:2px 0;border-radius:6px;font-size:12px;font-weight:600;
                border:1px solid transparent;transition:all 0.3s; }
    .sb-idle    { background:#0d0d1a;border-color:#1a1a2e;color:#444 !important; }
    .sb-running { background:#1a1500;border-color:#554400;color:#ffcc00 !important;
                  animation:pulse-yellow 1.2s infinite; }
    .sb-done    { background:#001a00;border-color:#224422;color:#44cc44 !important; }
    .sb-error   { background:#1a0000;border-color:#441111;color:#cc4444 !important; }
    .sb-count   { margin-left:auto;font-size:10px;color:#444 !important;
                  background:#ffffff11;padding:1px 6px;border-radius:8px; }
    .reason-line { font-size:10px;color:#334 !important;padding:2px 0 2px 10px;
                   border-left:2px solid #1a1a2e;margin:1px 0;line-height:1.4; }
    </style>
    """, unsafe_allow_html=True)

    st.sidebar.markdown(
        "<h2 style='margin:0;font-size:18px;font-weight:900;"
        "background:linear-gradient(90deg,#6a9fff,#ff6a9f);"
        "-webkit-background-clip:text;-webkit-text-fill-color:transparent'>"
        "⚡ AI Sales Engine</h2>"
        "<p style='font-size:11px;color:#444;margin:2px 0'>Autonomous Revenue Ops</p>",
        unsafe_allow_html=True
    )

    # API status
    st.sidebar.markdown("---")
    if API_KEY == "YOUR_APIFREELLM_KEY_HERE":
        st.sidebar.error("❌ API key missing — line 50")
    else:
        st.sidebar.success("✅ apifreellm connected")

    email_ok = EMAIL_USER != "your_email@outlook.com"
    if email_ok:
        st.sidebar.success(f"✅ Outlook: {EMAIL_USER}")
    else:
        st.sidebar.warning("⚠️ Email not configured — set EMAIL_USER/EMAIL_PASS")

    # Product context input
    st.sidebar.markdown("---")
    st.sidebar.markdown("**What are you selling?**")
    st.sidebar.text_area(
        "Product / Service",
        value=st.session_state.get("product_context",""),
        placeholder="e.g. AI-powered sales forecasting SaaS for mid-market B2B companies in India",
        height=80,
        label_visibility="collapsed",
        key="product_context"
    )
    # key="product_context" writes directly to session_state — no manual sync needed

    # Agent nodes
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Agent Status**")
    statuses = st.session_state.get("agent_statuses",{})
    counts   = st.session_state.get("agent_counts",{})
    dot = {"idle":"⚪","running":"🟡","done":"🟢","error":"🔴"}
    agents = [
        ("Manager","🧠"),("Research","🔍"),("Qualification","📊"),
        ("Pipeline Manager","📋"),("Outreach","✉️"),("Personalization","🎯"),
        ("Monitoring","👁️"),("Recovery","🚨"),("Escalation","⚠️"),
        ("Marketing Intelligence","📈"),("Reporting","📄"),
    ]
    for name, icon in agents:
        s  = statuses.get(name,"idle")
        c  = counts.get(name,0)
        d  = dot.get(s,"⚪")
        cs = f'<span class="sb-count">{c}</span>' if c else ''
        st.sidebar.markdown(
            f'<div class="sb-agent sb-{s}">{d}{icon} {name}{cs}</div>',
            unsafe_allow_html=True
        )

    # Quick stats
    if df is not None and len(df) > 0:
        st.sidebar.markdown("---")
        st.sidebar.markdown("**Pipeline**")
        c1,c2 = st.sidebar.columns(2)
        c1.metric("Total",   len(df))
        c2.metric("🔥 Hot",  len(df[df["qualification_tier"]=="Hot"]))
        c1.metric("⚠️ Risk", len(df[df["pipeline_status"].isin(["At Risk","Critical"])]))
        c2.metric("✅ Won",  len(df[df["pipeline_status"]=="Won"]))

    # Manager reasoning
    reasoning = st.session_state.get("manager_reasoning",[])
    if reasoning:
        st.sidebar.markdown("---")
        st.sidebar.markdown("**Manager Reasoning**")
        for line in reasoning[-6:]:
            st.sidebar.markdown(
                f'<div class="reason-line">{line}</div>',
                unsafe_allow_html=True
            )

# =============================================================
# ── TAB 1: PIPELINE ───────────────────────────────────────────
# =============================================================

def render_pipeline_tab(df):
    if df is None or len(df) == 0:
        st.markdown("""
        <div style="text-align:center;padding:60px 20px;color:#333">
        <div style="font-size:48px">📂</div>
        <div style="font-size:18px;margin:12px 0">No leads loaded</div>
        <div style="font-size:13px">Upload a CSV above or generate test data in Tab 4</div>
        </div>
        """, unsafe_allow_html=True)
        return

    # Top metrics
    total = len(df)
    hot   = len(df[df["qualification_tier"]=="Hot"])
    warm  = len(df[df["qualification_tier"]=="Warm"])
    cold  = len(df[df["qualification_tier"]=="Cold"])
    risk  = len(df[df["pipeline_status"].isin(["At Risk","Critical"])])
    won   = len(df[df["pipeline_status"]=="Won"])
    esc   = len(df[df["escalation_flag"]=="true"])

    c1,c2,c3,c4,c5,c6,c7 = st.columns(7)
    c1.metric("Total",       total)
    c2.metric("🔥 Hot",      hot)
    c3.metric("🟡 Warm",     warm)
    c4.metric("🔵 Cold",     cold)
    c5.metric("⚠️ At Risk",  risk)
    c6.metric("✅ Won",       won)
    c7.metric("🚨 Escalated",esc)

    # Errors from last run
    errors = st.session_state.get("run_errors",[])
    if errors:
        with st.expander(f"⚠️ {len(errors)} errors from last run"):
            for e in errors:
                st.warning(f"{e['time']} — {e['agent']} [{e['lead_id']}]: {e['error']}")

    st.divider()

    # Stage pipeline — horizontal scroll cards
    st.markdown("### Pipeline by Stage")
    STAGES = ["New","Researched","Qualified","Outreach Sent","Personalized",
              "Contacted","Engaged","At Risk","In Recovery","Escalated","Won","Lost"]
    STAGE_COLORS = {
        "New":"#1a1a2e","Researched":"#0a1a2a","Qualified":"#0a2a1a",
        "Outreach Sent":"#2a2a0a","Personalized":"#1a0a2a","Contacted":"#1a1a2e",
        "Engaged":"#003300","At Risk":"#2a1500","In Recovery":"#2a0000",
        "Escalated":"#3a0000","Won":"#003a00","Lost":"#1a1a1a",
    }
    TIER_COLORS = {"Hot":"#ff6b6b","Warm":"#ffd93d","Cold":"#74b9ff","":"#555"}

    active = [s for s in STAGES if len(df[df["current_stage"]==s])>0]
    if active:
        n = min(len(active), 5)
        cols = st.columns(n)
        for i, stage in enumerate(active):
            sdf  = df[df["current_stage"]==stage]
            col  = cols[i % n]
            sc   = STAGE_COLORS.get(stage,"#1a1a2e")
            with col:
                st.markdown(f"""
                <div style="background:{sc};border-radius:8px;padding:8px 12px;
                margin-bottom:8px;border:1px solid #ffffff11">
                <b style="font-size:12px;color:#aaa">{stage}</b>
                <span style="float:right;background:#ffffff22;border-radius:10px;
                padding:1px 8px;font-size:11px;color:#fff">{len(sdf)}</span>
                </div>
                """, unsafe_allow_html=True)
                for _, row in sdf.iterrows():
                    tc = TIER_COLORS.get(str(row.get("qualification_tier","")), "#555")
                    st.markdown(f"""
                    <div style="background:#0a0a14;border:1px solid #1a1a2e;
                    border-left:3px solid {tc};border-radius:6px;
                    padding:8px;margin-bottom:5px">
                    <b style="font-size:11px;color:#ddd">{row.get('full_name','')}</b><br>
                    <span style="font-size:10px;color:#666">
                    {row.get('company_name','')} · {row.get('role_title','')}</span><br>
                    <span style="font-size:10px;color:{tc}">
                    {row.get('qualification_tier','—')} 
                    {f"· {row.get('qualification_score','')}pts" if row.get('qualification_score') else ''}</span>
                    </div>
                    """, unsafe_allow_html=True)

    st.divider()

    # Full table
    st.markdown("### Full Pipeline Table")
    dcols = ["lead_id","full_name","company_name","role_title","email",
             "qualification_tier","qualification_score","current_stage",
             "pipeline_status","urgency_score","escalation_flag",
             "outreach_subject","recovery_attempts","last_agent_run","last_updated_at"]
    disp = df[[c for c in dcols if c in df.columns]].copy()

    def color_tier(v):
        return {"Hot":"background:#3a1010;color:#ff6b6b",
                "Warm":"background:#3a3010;color:#ffd93d",
                "Cold":"background:#10203a;color:#74b9ff"}.get(str(v),"")
    def color_status(v):
        return {"Critical":"background:#3a0808;color:#ff4444",
                "At Risk":"background:#3a2008;color:#ffaa44",
                "On Track":"background:#083a08;color:#44ff44",
                "Won":"background:#083a08;color:#00ff00",
                "Lost":"background:#1a1a1a;color:#555"}.get(str(v),"")

    # pandas 2.x: use .map() (applymap removed in pandas 2.1)
    style_kwargs = {}
    if "qualification_tier" in disp.columns:
        disp = disp.copy()
    styled = disp.style
    if "qualification_tier" in disp.columns:
        styled = styled.map(color_tier,   subset=["qualification_tier"])
    if "pipeline_status" in disp.columns:
        styled = styled.map(color_status, subset=["pipeline_status"])
    st.dataframe(styled, use_container_width=True, height=350)

    st.divider()

    # Lead cards
    st.markdown("### Lead Detail Cards")
    TIER_ICON = {"Hot":"🔥","Warm":"🟡","Cold":"🔵"}
    for _, row in df.iterrows():
        ti   = TIER_ICON.get(str(row.get("qualification_tier","")),"⚪")
        stat = str(row.get("pipeline_status",""))
        stat_badge = (
            "🔴" if stat=="Critical" else
            "🟠" if stat=="At Risk"  else
            "🟢" if stat=="On Track" else
            "✅" if stat=="Won"      else ""
        )
        with st.expander(
            f"{ti} {row.get('full_name','')} — {row.get('company_name','')} "
            f"· {row.get('current_stage','New')} {stat_badge}"
        ):
            c1,c2,c3 = st.columns(3)
            with c1:
                st.markdown("**Contact**")
                st.write(f"📧 {row.get('email','—')}")
                st.write(f"📱 {row.get('phone','—')}")
                st.write(f"🏢 {row.get('role_title','—')}")
                st.markdown("**Company**")
                st.write(f"Industry: {row.get('industry','—')}")
                st.write(f"Size: {row.get('company_size','—')}")
                st.write(f"Model: {row.get('business_model','—')}")
                st.caption(f"{row.get('company_summary','—')}")
            with c2:
                st.markdown("**Qualification**")
                s = row.get("qualification_score","—")
                t = row.get("qualification_tier","—")
                st.write(f"Score: **{s}/100** — {t}")
                st.write(f"{row.get('tier_reasoning','—')}")
                st.write(f"Pain: {row.get('pain_point_1','—')}")
                st.write(f"Hook: {row.get('conversation_hook','—')}")
                st.markdown("**Pipeline**")
                st.write(f"Stage: {row.get('current_stage','—')}")
                st.write(f"Status: {row.get('pipeline_status','—')}")
                st.write(f"Urgency: {row.get('urgency_score','—')}/10")
            with c3:
                st.markdown("**Outreach**")
                subj = row.get("outreach_subject","")
                if subj:
                    st.write(f"Subject: *{subj}*")
                    st.write(f"Sent: {row.get('outreach_sent_at','—')}")
                    st.write(f"Follow-up #: {row.get('follow_up_number',0)}")
                else:
                    st.write("No outreach sent yet")
                st.markdown("**Recovery & Escalation**")
                st.write(f"Attempts: {row.get('recovery_attempts',0)}")
                st.write(f"Strategy: {row.get('recovery_strategy','—')}")
                st.write(f"Confidence: {row.get('recovery_confidence_pct','—')}")
                if str(row.get("escalation_flag",""))=="true":
                    st.error(f"🚨 {row.get('escalation_reason','—')}")

# =============================================================
# ── TAB 2: AGENT CONTROL ROOM — real flowchart ────────────────
# =============================================================

def render_control_room_tab():
    st.markdown("### 🤖 Agent Orchestration Flowchart")
    st.caption("Live view — nodes pulse yellow when running, turn green when done")

    statuses = st.session_state.get("agent_statuses",{})
    counts   = st.session_state.get("agent_counts",{})
    flows    = st.session_state.get("data_flow_log",[])

    def node_style(name):
        s = statuses.get(name,"idle")
        styles = {
            "idle":    "background:#0d0d1a;border:2px solid #1e1e2e;color:#444",
            "running": "background:#1a1500;border:2px solid #aa8800;color:#ffcc00;"
                       "animation:pulse-yellow 1.2s infinite",
            "done":    "background:#001500;border:2px solid #226622;color:#44cc44;"
                       "animation:pulse-green 2s ease",
            "error":   "background:#150000;border:2px solid #662222;color:#cc4444",
        }
        return styles.get(s, styles["idle"])

    def node_html(name, icon, width="160px"):
        s     = statuses.get(name,"idle")
        c     = counts.get(name,0)
        style = node_style(name)
        count_html = f'<div style="font-size:10px;color:#555;margin-top:2px">{c} leads</div>' if c else ''
        dot   = {"idle":"⚪","running":"🟡","done":"🟢","error":"🔴"}.get(s,"⚪")
        return f"""
        <div style="{style};border-radius:10px;padding:10px 14px;
        text-align:center;min-width:{width};display:inline-block;
        font-family:'Syne',sans-serif;transition:all 0.3s">
          <div style="font-size:18px">{icon}</div>
          <div style="font-size:11px;font-weight:700;margin:3px 0">{dot} {name}</div>
          {count_html}
        </div>"""

    def arrow_v(label="", active=False):
        col = "#aa8800" if active else "#222244"
        return f"""
        <div style="display:flex;flex-direction:column;align-items:center;
        padding:2px 0;color:{col}">
          <div style="width:2px;height:20px;background:{col};
          position:relative;overflow:hidden">
          {'<div style="position:absolute;width:100%;height:40%;background:#ffcc88;animation:flow-down 0.8s linear infinite"></div>' if active else ''}
          </div>
          <div style="font-size:14px">▼</div>
          <div style="font-size:9px;color:#333">{label}</div>
        </div>"""

    def arrow_h(label="", active=False):
        col = "#aa8800" if active else "#222244"
        return f"""
        <div style="display:flex;align-items:center;padding:0 4px;color:{col}">
          <div style="height:2px;width:30px;background:{col};
          position:relative;overflow:hidden">
          {'<div style="position:absolute;height:100%;width:40%;background:#ffcc88;animation:flow-right 0.8s linear infinite"></div>' if active else ''}
          </div>
          <span style="font-size:12px">▶</span>
          <span style="font-size:9px;color:#333;margin-left:2px">{label}</span>
        </div>"""

    # Determine active flows
    active_agent = st.session_state.get("active_agent")
    def is_active(from_a, to_a):
        return active_agent in (from_a, to_a)

    # ── FLOWCHART HTML ──
    fc = f"""
    <div style="background:#07070f;border:1px solid #1a1a2e;border-radius:12px;
    padding:24px;overflow-x:auto;animation:fade-in 0.5s ease">

      <!-- ROW 1: Manager -->
      <div style="display:flex;justify-content:center;margin-bottom:4px">
        {node_html("Manager","🧠","180px")}
      </div>
      <div style="display:flex;justify-content:center">
        {arrow_v("orchestrates", is_active("Manager","Research"))}
      </div>

      <!-- ROW 2: Research + Qualification (parallel) -->
      <div style="display:flex;justify-content:center;align-items:center;gap:8px;margin-bottom:4px">
        {node_html("Research","🔍")}
        <div style="display:flex;flex-direction:column;align-items:center;color:#1a3a5a;font-size:10px">
          <span>parallel</span>
          <span style="font-size:18px;color:#222244">⟷</span>
        </div>
        {node_html("Qualification","📊")}
      </div>
      <div style="display:flex;justify-content:center">
        {arrow_v("then", is_active("Qualification","Pipeline Manager"))}
      </div>

      <!-- ROW 3: Pipeline Manager -->
      <div style="display:flex;justify-content:center;margin-bottom:4px">
        {node_html("Pipeline Manager","📋","180px")}
      </div>
      <div style="display:flex;justify-content:center">
        {arrow_v("then", is_active("Pipeline Manager","Outreach"))}
      </div>

      <!-- ROW 4: Outreach + Personalization (parallel) -->
      <div style="display:flex;justify-content:center;align-items:center;gap:8px;margin-bottom:4px">
        {node_html("Outreach","✉️")}
        <div style="display:flex;flex-direction:column;align-items:center;color:#1a3a5a;font-size:10px">
          <span>parallel</span>
          <span style="font-size:18px;color:#222244">⟷</span>
        </div>
        {node_html("Personalization","🎯")}
      </div>
      <div style="display:flex;justify-content:center">
        {arrow_v("then", is_active("Personalization","Monitoring"))}
      </div>

      <!-- ROW 5: Monitoring -->
      <div style="display:flex;justify-content:center;margin-bottom:4px">
        {node_html("Monitoring","👁️","180px")}
      </div>
      <div style="display:flex;justify-content:center">
        {arrow_v("flags →", is_active("Monitoring","Recovery"))}
      </div>

      <!-- ROW 6: Recovery + Escalation (parallel) -->
      <div style="display:flex;justify-content:center;align-items:center;gap:8px;margin-bottom:4px">
        {node_html("Recovery","🚨")}
        <div style="display:flex;flex-direction:column;align-items:center;color:#1a3a5a;font-size:10px">
          <span>parallel</span>
          <span style="font-size:18px;color:#222244">⟷</span>
        </div>
        {node_html("Escalation","⚠️")}
      </div>
      <div style="display:flex;justify-content:center">
        {arrow_v("then", is_active("Escalation","Marketing Intelligence"))}
      </div>

      <!-- ROW 7: Marketing Intelligence -->
      <div style="display:flex;justify-content:center;margin-bottom:4px">
        {node_html("Marketing Intelligence","📈","200px")}
      </div>
      <div style="display:flex;justify-content:center">
        {arrow_v("finally", is_active("Marketing Intelligence","Reporting"))}
      </div>

      <!-- ROW 8: Reporting -->
      <div style="display:flex;justify-content:center;margin-bottom:4px">
        {node_html("Reporting","📄","180px")}
      </div>

      <!-- Legend -->
      <div style="display:flex;justify-content:center;gap:20px;margin-top:20px;
      border-top:1px solid #1a1a2e;padding-top:12px">
        <span style="font-size:11px;color:#444">⚪ Idle</span>
        <span style="font-size:11px;color:#aa8800">🟡 Running</span>
        <span style="font-size:11px;color:#226622">🟢 Done</span>
        <span style="font-size:11px;color:#662222">🔴 Error</span>
      </div>
    </div>
    """
    st.markdown(fc, unsafe_allow_html=True)

    # Data flow log
    if flows:
        st.divider()
        st.markdown("### Data Flow Log")
        flow_df = pd.DataFrame(flows)
        st.dataframe(flow_df, use_container_width=True, height=200)

    # Manager reasoning
    reasoning = st.session_state.get("manager_reasoning",[])
    if reasoning:
        st.divider()
        st.markdown("### Manager Reasoning Trail")
        for line in reasoning:
            st.markdown(
                f'<p style="color:#334466;font-size:11px;font-family:JetBrains Mono,monospace;'
                f'border-left:2px solid #1a1a3a;padding-left:10px;margin:3px 0">{line}</p>',
                unsafe_allow_html=True
            )

    # Agent call logs
    logs = st.session_state.get("agent_logs",[])
    if logs:
        st.divider()
        with st.expander(f"📋 Raw Agent Logs ({len(logs)} API calls)"):
            st.dataframe(pd.DataFrame(logs), use_container_width=True)

# =============================================================
# ── TAB 3: REPORTS ────────────────────────────────────────────
# =============================================================

def render_reports_tab():
    st.markdown("## 📄 Daily Report & Intelligence")
    report = st.session_state.get("last_report")
    mkt    = st.session_state.get("last_marketing")

    if not report:
        st.info("Run the engine to generate the daily report.")
        return

    score  = report.get("pipeline_health_score",0)
    col    = "#44cc44" if score>=70 else "#ffcc00" if score>=40 else "#cc4444"
    st.markdown(f"""
    <div style="background:#0d0d1a;border:2px solid {col};border-radius:12px;
    padding:20px;text-align:center;margin-bottom:24px">
    <div style="font-size:52px;font-weight:900;color:{col};font-family:Syne">{score}</div>
    <div style="font-size:13px;color:#666;margin:4px 0">Pipeline Health / 100</div>
    <div style="font-size:13px;color:#aaa">{report.get('health_explanation','')}</div>
    </div>
    """, unsafe_allow_html=True)

    nums = report.get("three_key_numbers",[])
    if nums:
        cols = st.columns(len(nums))
        for i,n in enumerate(nums):
            cols[i].metric(n.get("metric",""),n.get("value",""),n.get("context",""))

    st.divider()
    c1,c2 = st.columns(2)

    with c1:
        st.markdown("### ⚠️ Needs Attention")
        for item in report.get("needs_attention",[]):
            with st.container(border=True):
                st.markdown(f"**{item.get('lead_name','')}**")
                st.write(f"🔍 {item.get('risk_reason','')}")
                st.write(f"✅ {item.get('action_taken','')}")
                st.error(f"⚡ {item.get('next_24h','')}")
        if not report.get("needs_attention"):
            st.success("No urgent deals right now.")

    with c2:
        st.markdown("### 🚀 Positive Momentum")
        for item in report.get("positive_momentum",[]):
            with st.container(border=True):
                st.markdown(f"**{item.get('lead_name','')}**")
                st.success(f"📈 {item.get('signal','')}")
        if not report.get("positive_momentum"):
            st.info("Signals building — check back after next run.")

    escs = report.get("escalations_awaiting",[])
    if escs:
        st.divider()
        st.markdown("### 🚨 Escalations — Decision Needed")
        for esc in escs:
            uc = {"Immediate":"#ff4444","Today":"#ffaa44","This Week":"#ffff44"}.get(
                esc.get("urgency",""),"#888")
            with st.container(border=True):
                st.markdown(
                    f'<span style="color:{uc};font-weight:700">'
                    f'{esc.get("urgency","")} — {esc.get("lead_id","")}</span>',
                    unsafe_allow_html=True)
                st.write(f"**Why:** {esc.get('reason','')}")
                st.write(f"**Decide:** {esc.get('decision_needed','')}")
                st.write(f"**By:** {esc.get('deadline','')}")
                st.caption(f"Fallback: {esc.get('fallback_action','')}")

    auto = report.get("autonomous_actions_completed",[])
    if auto:
        st.divider()
        st.markdown("### 🤖 Autonomous Actions Completed")
        for a in auto:
            st.markdown(f"✅ {a}")

    if mkt:
        st.divider()
        st.markdown("### 📈 Marketing Intelligence")
        for ins in mkt.get("insights",[]):
            cc = {"High":"#44cc44","Medium":"#ffcc00","Low":"#cc8844"}.get(
                ins.get("confidence",""),"#888")
            with st.container(border=True):
                st.markdown(f"**{ins.get('finding','')}**")
                st.caption(f"Evidence: {ins.get('evidence','')}")
                st.success(f"→ {ins.get('recommendation','')}")
                st.markdown(
                    f'<span style="color:{cc};font-size:10px">'
                    f'Confidence: {ins.get("confidence","")}</span>',
                    unsafe_allow_html=True)
        c1,c2 = st.columns(2)
        c1.info(f"**Best Subject Formula:** {mkt.get('best_subject_formula','—')}")
        c2.error(f"**Stop Doing:** {mkt.get('stop_doing_immediately','—')}")

    tomorrow = report.get("tomorrows_plan",{})
    if tomorrow:
        st.divider()
        st.markdown("### 📅 Tomorrow's Plan")
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("**System will do autonomously:**")
            for a in tomorrow.get("autonomous_actions",[]):
                st.markdown(f"🤖 {a}")
        with c2:
            st.markdown("**You need to decide:**")
            for h in tomorrow.get("human_decisions_needed",[]):
                st.markdown(f"👤 {h}")

    focus = report.get("focus_sentence","")
    if focus:
        st.divider()
        st.markdown(f"""
        <div style="background:#0a1a0a;border:1px solid #224422;border-radius:8px;
        padding:16px 20px;text-align:center">
        <b style="color:#44cc44;font-size:14px">{focus}</b>
        </div>
        """, unsafe_allow_html=True)

    st.divider()
    st.download_button(
        "⬇️ Download Full Report (JSON)",
        data=json.dumps(report, indent=2),
        file_name=f"report_{date.today()}.json",
        mime="application/json"
    )

# =============================================================
# ── TAB 4: TEST DATA GENERATOR ───────────────────────────────
# =============================================================

DUMMY_PROMPT = """
Generate exactly {n} realistic Indian B2B sales leads.
Industries to include: {industries}

Requirements:
- Realistic Indian names
- Real-sounding Indian company names (mix of startups and established)
- Professional roles: CTO, VP Sales, CFO, Head of Operations, 
  Director of Engineering, VP Marketing, CEO, COO, Product Head
- Professional email: firstname.lastname@companyname.com
- Indian phone: +91 XXXXX XXXXX format
- No two leads from same company
- Mix of company sizes: startups, SMBs, mid-market

Return ONLY valid JSON:
{{
  "leads": [
    {{
      "lead_id": "L001",
      "full_name": "Indian full name",
      "company_name": "Indian company name",
      "role_title": "specific B2B role",
      "email": "firstname.lastname@company.com",
      "phone": "+91 XXXXX XXXXX"
    }}
  ]
}}

Generate exactly {n} leads. Make them diverse.
"""

def render_test_data_tab():
    st.markdown("## 🎲 Test Data Generator")
    st.markdown(
        "Generate realistic Indian B2B leads using AI. "
        "Download → Upload above → Run Engine."
    )

    with st.container(border=True):
        st.markdown("**CSV Format — only these 6 columns required:**")
        st.code("lead_id, full_name, company_name, role_title, email, phone")
        st.caption(
            "Column names are flexible — the system recognises common alternatives "
            "like 'name', 'company', 'role', 'title', 'mobile' etc."
        )

    st.divider()
    c1,c2 = st.columns(2)
    with c1:
        n = st.slider("Leads to generate", 3, 20, 8)
    with c2:
        industries = st.multiselect(
            "Industries",
            ["SaaS","Fintech","Logistics","Ecommerce","Healthtech",
             "Edtech","Manufacturing","BFSI","IT Services","D2C"],
            default=["SaaS","Fintech","Ecommerce","Logistics"]
        )

    if st.button("🤖 Generate Leads with AI", type="primary"):
        ind_str = ", ".join(industries) if industries else "mixed Indian B2B"
        with st.spinner(f"Generating {n} realistic Indian B2B leads..."):
            result = call_llm(
                DUMMY_PROMPT.format(n=n, industries=ind_str),
                agent_name="DataGenerator"
            )
        if result and "leads" in result:
            gdf = pd.DataFrame(result["leads"])
            for col in ["lead_id","full_name","company_name","role_title","email","phone"]:
                if col not in gdf.columns:
                    gdf[col] = ""
            gdf = gdf[["lead_id","full_name","company_name","role_title","email","phone"]]
            st.success(f"✅ {len(gdf)} leads generated")
            st.dataframe(gdf, use_container_width=True)
            st.download_button(
                "⬇️ Download Leads CSV",
                data=gdf.to_csv(index=False).encode(),
                file_name="test_leads.csv",
                mime="text/csv"
            )
        else:
            st.error("Generation failed — check API key and try again.")

    st.divider()
    st.markdown("### 📋 Download Blank Template")
    tmpl = pd.DataFrame([{
        "lead_id":"L001","full_name":"Priya Sharma",
        "company_name":"Razorpay","role_title":"VP of Sales",
        "email":"priya.sharma@razorpay.com","phone":"+91 98765 43210"
    }])
    st.dataframe(tmpl, use_container_width=True)
    st.download_button(
        "⬇️ Download Template CSV",
        data=tmpl.to_csv(index=False).encode(),
        file_name="leads_template.csv",
        mime="text/csv"
    )

# =============================================================
# ── MAIN APP ──────────────────────────────────────────────────
# =============================================================

def main():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

    df = st.session_state.get("pipeline_df")
    render_sidebar(df)

    # Header
    st.markdown("""
    <div style="padding:12px 0 4px 0;animation:fade-in 0.6s ease">
    <h1 style="margin:0;font-size:26px;font-weight:900;
    background:linear-gradient(90deg,#6a9fff,#ff6a9f,#ffcc00);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent">
    ⚡ Autonomous AI Sales & Revenue Engine</h1>
    <p style="color:#333;margin:2px 0;font-size:12px">
    11 Agents · Manager Orchestrated · Real Outlook Email · Live CSV Updates</p>
    </div>
    """, unsafe_allow_html=True)

    # ── UPLOAD + RUN ROW ─────────────────────────────────────
    st.markdown("""
    <div style="background:#0d0d1a;border:1px solid #1a1a2e;
    border-radius:10px;padding:16px;margin:12px 0">
    """, unsafe_allow_html=True)

    up_col, run_col = st.columns([3, 1])

    with up_col:
        uploaded = st.file_uploader(
            "Upload Leads CSV",
            type=["csv"],
            help="Needs: lead_id, full_name, company_name, role_title, email, phone "
                 "(flexible column names accepted)",
            key="csv_upload",
            label_visibility="visible"
        )
        if uploaded:
            if (df is None or
                    st.session_state.get("_last_upload") != uploaded.name):
                df, warnings = load_csv(uploaded)
                orig = f"uploaded_{uploaded.name}"
                try:
                    uploaded.seek(0)
                    with open(orig,"wb") as fw:
                        fw.write(uploaded.read())
                    st.session_state["original_path"] = orig
                except Exception:
                    pass
                st.session_state["pipeline_df"]  = df
                st.session_state["_last_upload"] = uploaded.name
                save_pipeline(df)
                for w in warnings:
                    st.warning(f"⚠️ {w}")
                st.success(f"✅ {len(df)} leads loaded")

    with run_col:
        st.markdown("<br>", unsafe_allow_html=True)
        no_product = not st.session_state.get("product_context","").strip()
        no_leads   = df is None or len(df) == 0
        running    = st.session_state.get("engine_running", False)

        if no_product:
            st.warning("Set product in sidebar first")
        elif no_leads:
            st.info("Upload CSV to run")
        elif running:
            st.button("⏳ Running...", disabled=True, use_container_width=True)
        else:
            run_clicked = st.button("🚀 Run Engine", type="primary", use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)

    # ── FULL-WIDTH PROGRESS AREA — above tabs, always visible ──
    progress_area = st.container()

    # Run complete status bar
    if st.session_state.get("run_complete") and not st.session_state.get("engine_running"):
        report  = st.session_state.get("last_report",{})
        score   = report.get("pipeline_health_score","—")
        focus   = report.get("focus_sentence","")
        errors  = st.session_state.get("run_errors",[])
        err_str = f" · {len(errors)} errors" if errors else ""
        with progress_area:
            st.markdown(f"""
            <div style="background:#001500;border:1px solid #224422;
            border-radius:8px;padding:10px 16px;margin:4px 0 8px 0">
            <span style="color:#44cc44;font-weight:700">
            ✅ Run complete · Pipeline Health: {score}/100{err_str}</span>
            <span style="color:#668866;font-size:12px;margin-left:16px">{focus}</span>
            </div>
            """, unsafe_allow_html=True)
            if os.path.exists(PIPELINE_FILE):
                with open(PIPELINE_FILE,"rb") as fd:
                    st.download_button(
                        "⬇️ Download Live Pipeline CSV",
                        data=fd.read(),
                        file_name="pipeline_live.csv",
                        mime="text/csv",
                        key="dl_pipeline"
                    )

    # Actually run the engine — status boxes render into progress_area
    if not no_product and not no_leads and not running:
        if "run_clicked" in dir() and run_clicked:
            with progress_area:
                df = run_full_engine(df)
            st.session_state["pipeline_df"] = df
            st.rerun()

    # ── 4 TABS ───────────────────────────────────────────────
    t1,t2,t3,t4 = st.tabs([
        "📊 Pipeline",
        "🤖 Agent Control Room",
        "📄 Reports",
        "🎲 Test Data"
    ])

    with t1: render_pipeline_tab(st.session_state.get("pipeline_df"))
    with t2: render_control_room_tab()
    with t3: render_reports_tab()
    with t4: render_test_data_tab()


if __name__ == "__main__":
    main()