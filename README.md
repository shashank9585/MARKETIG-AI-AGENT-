# Autonomous Sales AI Agent 

# ⚡ Autonomous Sales and Revenue Engine 
Autonomous-Sales-AI-Agent

> A multi-agent AI system that simulates and automates the entire B2B sales pipeline — from lead research to outreach, monitoring, and reporting.

---

## 🧠 Overview

This project is an **autonomous revenue operations engine** built using Python and Streamlit.

It mimics how a real sales team operates by using **11 specialized AI agents**, each responsible for a stage in the pipeline — working together under a central **Manager agent**.

Instead of just generating leads or emails, this system:

* Understands leads deeply
* Qualifies and prioritizes them
* Executes personalized outreach
* Tracks pipeline progression
* Generates executive-level insights

---

## 🚀 Key Features

### 🤖 Multi-Agent Architecture

A coordinated system of 11 agents:

* 🧠 Manager — orchestrates flow
* 🔍 Research — enriches lead data
* 📊 Qualification — scores & tiers leads
* 📋 Pipeline Manager — manages deal stages
* ✉️ Outreach — sends personalized emails
* 🎯 Personalization — crafts messaging
* 👁️ Monitoring — tracks engagement
* 🚨 Recovery — handles inactive leads
* ⚠️ Escalation — flags critical deals
* 📈 Marketing Intelligence — extracts insights
* 📄 Reporting — generates daily summaries

---

### 📊 Intelligent Pipeline Management

* Dynamic lead stages (New → Won/Lost)
* Qualification scoring (Hot / Warm / Cold)
* Risk detection (At Risk / Critical)
* Escalation & recovery tracking

---

### 📧 AI-Powered Outreach

* Personalized subject lines
* Context-aware messaging hooks
* Pain-point-driven communication
* Follow-up tracking

---

### 📄 Executive Reporting

Generates structured JSON reports including:

* Pipeline health score
* Key metrics (conversion, engagement)
* Leads needing attention
* Positive momentum signals
* Tomorrow’s action plan

---

### 🖥️ Interactive Control Room (Streamlit UI)

* Live pipeline dashboard
* Agent orchestration flowchart
* Real-time agent status tracking
* Data flow logs
* Test data generator

---

## 🧩 System Architecture

```text
Leads CSV
   ↓
Research Agent
   ↓
Qualification Agent
   ↓
Pipeline Manager
   ↓
Outreach + Personalization
   ↓
Monitoring
   ↓
Recovery / Escalation
   ↓
Reporting (JSON)
   ↓
Streamlit UI (Control Room)
```

---

## 📂 Project Structure

```
.
├── app.py                  # Main Streamlit app
├── agents/                 # Agent logic (modular)
├── data/
│   ├── pipeline.csv        # Live pipeline data
│   └── template.csv        # Input format
├── reports/
│   └── report.json         # Generated reports
├── utils/
│   ├── llm.py              # LLM calls
│   ├── pipeline.py         # Data handling
│   └── scoring.py          # Qualification & health logic
└── README.md
```

---

## 📥 Input Format (CSV)

Minimum required columns:

```
lead_id, full_name, company_name, role_title, email, phone
```

Optional enriched fields:

* industry
* company_size
* pain_point_1
* tech_stack_inferred
* qualification_score
* pipeline_status
* etc.

---

## ⚙️ Setup & Run

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/ai-sales-engine.git
cd ai-sales-engine
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

Set your API key inside the app:

```python
API_KEY = "your_apifreellm_key"
```

(Optional)

```python
EMAIL_USER = "your_email@outlook.com"
EMAIL_PASS = "your_password"
```

---

### 4. Run the app

```bash
streamlit run app.py
```

---

## 🎮 How to Use

1. Enter your **product/service** in the sidebar
2. Upload a **CSV of leads**
3. Click **“Run Engine”**
4. Watch agents process leads in real-time
5. Explore:

   * 📊 Pipeline tab
   * 🤖 Control Room
   * 📄 Reports

---

## 🧪 Test Data Generator

Built-in AI generator to create realistic Indian B2B leads:

* Select industries
* Choose number of leads
* Download ready-to-use CSV

---

## 📈 Current Capabilities

* End-to-end pipeline simulation
* Multi-agent orchestration
* Intelligent reporting
* UI-based monitoring

---

## ⚠️ Limitations (Current Version)

* Limited real engagement tracking
* Simulated pipeline progression
* No external CRM/email integrations yet

---

## 🔮 Future Improvements

* Real email tracking (opens, replies)
* Behavioral simulation engine
* Learning loop (adaptive outreach)
* CRM integrations (HubSpot, Salesforce)
* Advanced scoring models

---

## 💡 Why This Project?

Most tools today:

* Generate leads OR
* Send emails OR
* Track pipelines

This system aims to:

> ⚡ Combine all of them into a **single autonomous engine**

---

## 🏁 Final Thought

This is not just a dashboard or automation script.

It’s an attempt to build:

> 🤖 **A self-operating AI sales team**

---

## 📬 Contact

Built by Shashank H E
Open to feedback, collaboration, and ideas 🚀
