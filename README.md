<div align="center">
  <img src="media/logos/full_logo_multiple.png" alt="DiagFlow Logo" width="300" />
</div>

# 🏥 DiagFlow — Automated CT/MRI Report Assignment Engine

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Database](https://img.shields.io/badge/Database-MSSQL%20%28Slis%29-003B57.svg)](https://learn.microsoft.com/en-us/sql/)
[![Optimization](https://img.shields.io/badge/Optimization-Google%20OR--Tools-4285F4.svg)](https://developers.google.com/optimization)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)](#license)

**DiagFlow** is an intelligent diagnostic assignment and decision-support engine developed for **Kosmoiatriki**. It automates the complex process of assigning CT and MRI medical imaging reports from Infomed's Slis system to diagnosticians using a 4-stage rule engine, dynamic routing rules, weighted multi-factor scoring, near-tie load balancing, and Google OR-Tools CP-SAT batch optimization.

> 💡 **Design Philosophy:** *Suggest, don't decide.*  
> Every assignment suggestion comes with complete transparency, displaying exactly which rules fired, score breakdowns per factor and full visibility into eliminated candidates with human-readable rejection reasons. Secretariat operators retain full authority to confirm suggestions or manually override them with one click. Every decision and human override is logged for auditing and future weight tuning.

---

## 📋 Table of Contents

- [✨ Key Features](#-key-features)
- [🏗️ System Architecture](#️-system-architecture)
- [⚙️ Engine Deep Dive](#️-engine-deep-dive)
  - [Rule Engine Pipeline](#1-4-stage-rule-engine-pipeline)
  - [Auto-Assignment System](#2-auto-assignment-system)
  - [Dual-Database Architecture](#3-dual-database-architecture)
  - [Two-Way Slis Sync Service](#4-two-way-slis-sync-service)
- [💻 User Interfaces](#-user-interfaces)
- [🛠️ Prerequisites](#️-prerequisites)
- [🚀 Installation & Setup Guide](#-installation--setup-guide)
  - [Option A: Running as a Web Application](#option-a-running-as-a-web-application)
  - [Option B: Building & Running Standalone Desktop EXE](#option-b-building--running-standalone-desktop-exe)
  - [📦 Deploying to Another PC](#-deploying-to-another-pc)
- [📊 Database Architecture & Schemas](#-database-architecture--schemas)
- [⚙️ Configuration & Environment Settings](#️-configuration--environment-settings)
- [📡 API Reference](#-api-reference)
- [📁 Project Structure](#-project-structure)
- [📐 PlantUML Architecture Diagrams](#-plantuml-architecture-diagrams)
- [📸 Screenshots](#-screenshots)
- [📄 License](#-license)

---

## ✨ Key Features

| Area | Feature | Description |
|------|---------|-------------|
| ⚙️ **Rule Engine** | **4-Stage Decision Pipeline** | Hard filters → weighted scoring → near-tie load balancing → solver pipeline with 100% decision transparency. |
| 📋 **Order Grouping** | **Same Order ID Consistency** | Proposes the same diagnostician for all exams sharing the same Order ID (`extracode`) to ensure diagnostic consistency. |
| 🧮 **Optimization** | **Google OR-Tools CP-SAT** | Global constraint solver for batch assignments, maximizing total score while enforcing daily capacity & modality quotas. |
| ⚖️ **Load Balancing** | **Near-Tie Rotation** | Candidates within a configurable score tolerance (default 5%) are ranked by workload, preventing individual burnout. |
| 🔄 **Session Offset** | **Real-Time Workload Tracking** | Tracks uncommitted suggestions within an active session so sequential proposals distribute workload evenly before confirmation. |
| ⚡ **Auto-Assignments** | **Dynamic Routing Rules** | Automatically assigns exclusive doctor partnerships, lab-specific exam codes (e.g. Arthrografies, TMJ, Spectroscopies), and Παμμακάριστος on-call rotation. |
| 🛡️ **Hard Constraints** | **Dynamic Quotas & Labs** | Enforces leave calendars, weekday quotas, modality limits (CT/MRI max counts), exclusive lab assignments, and skill proficiencies. |
| 🔄 **Slis Synchronization** | **Two-Way Integration** | Pulls unassigned exams from Slis (past 3 days), pushes confirmed local assignments back, and runs daily 3 AM background master data syncs via APScheduler. |
| 🖥️ **Secretariat Dashboard** | **4-Tab Interface** | `index.html` dashboard with pending, assigned, dashboard, and Slis search tabs (date range search [default 7 days] & reassignment by Order ID, Patient, Doctor, Diagnostician), instant suggestions, rule breakdowns, alternative modals, and Slis push. |
| 🔐 **Admin Panel** | **Configuration Management** | Authenticated `admin.html` interface for managing diagnosticians, skills, exam catalog dictionary & bulk skill assignment (Εξετάσεις tab), doctor partnerships, availability calendars, dynamic routing rules, modality quotas, and scoring weights. |
| 📜 **Audit Trail** | **Decision Logging** | Complete history logging original suggestions, final assignments, override indicators, and reason comments. |
| 📦 **Desktop App** | **Standalone EXE Packaging** | PyInstaller build script bundling FastAPI and `pywebview` for native desktop execution without browser requirements. |

---

## 🏗️ System Architecture

DiagFlow follows a decoupled, modular architecture connecting Infomed's Slis database with a high-performance Python FastAPI server, an OR-Tools optimization engine, and clean static web interfaces.

```
                      ┌────────────────────────────────────────┐
                      │    Slis Production DB (MSSQL)          │  ← Production (pyodbc)
                      │    mock_slis.db (SQLite)               │  ← Development
                      └───────────────────┬────────────────────┘
                                   pull / │ \ push
                       ───────────────────┼────────────────────
                                          ▼
                      ┌────────────────────────────────────────┐
                      │        DiagFlow FastAPI Server         │
                      │                                        │
                      │  ┌──────────────────┐  ┌────────────┐  │
                      │  │  Slis Sync Svc   │◄─┤APScheduler │  │ (Daily 3 AM Cron)
                      │  └──────────────────┘  └────────────┘  │
                      │  ┌──────────────────────────────────┐  │
                      │  │ Assignment Service               │  │
                      │  │ Diagnostician Service            │  │
                      │  │ Παμμακάριστος Scheduler          │  │
                      │  └────────────────┬─────────────────┘  │
                      │                   │                    │
                      │  ┌────────────────▼─────────────────┐  │
                      │  │       Rule Engine Pipeline       │  │
                      │  │ Stage 0: Exclusive & Routing     │  │
                      │  │ Stage 1: Hard Filters            │  │
                      │  │ Stage 2: Weighted Scoring        │  │
                      │  │ Stage 3: Near-Tie Balancer       │  │
                      │  │ Stage 4: CP-SAT / Greedy Solver  │  │
                      │  └──────────────────────────────────┘  │
                      │  ┌──────────────────────────────────┐  │
                      │  │ df_* Tables (MSSQL) / SQLite(Dev)│  │
                      │  └──────────────────────────────────┘  │
                      └───────────────────┬────────────────────┘
                                          │ REST API (/api/*)
                                          │ Static Files (/)
                                          ▼
                      ┌────────────────────────────────────────┐
                      │       User Interface Layer             │
                      │  • Secretariat Dashboard (index.html)  │
                      │  • Admin Control Panel (admin.html)    │
                      │  • Desktop Window (pywebview EXE)      │
                      └────────────────────────────────────────┘
```

---

## ⚙️ Engine Deep Dive

### 1. 4-Stage Rule Engine Pipeline

The pipeline processes each pending medical exam through four distinct stages:

```
Pending Exam
    │
    ├─ Stage 0: Exclusive Partnership or Dynamic Routing Rule matched? ──yes──► Auto-Assignment
    │
    ▼
Stage 1: Hard Filters (Availability → Capacity → Modality Quotas → Modality → Skills → Exclusive Labs)
    │
    ▼
Stage 2: Weighted Scoring (Partnership + Patient History + Skills Bonus + Lab Preference + Capacity Ratio)
    │
    ▼
Stage 3: Near-Tie Load Balancing (Score tolerance group → sort by workload + session offset)
    │
    ▼
Stage 4: Solver (Greedy pick rank #1 for single exam, CP-SAT for batch optimization)
    │
    ▼
Assignment Suggestion + Score Breakdown + Alternatives List + Audit Trail Log
```

#### Stage 0: Direct Routing & Exclusive Partnerships
Exams issued by doctors with an **active exclusive partnership** or matching a **dynamic exam routing rule** bypass scoring and are assigned directly to the target diagnostician.

#### Stage 1: Hard Filters (Must Pass)
Candidates failing any hard filter are marked as **eliminated** for that exam. *Crucially, eliminated candidates are NOT hidden from the user*; they are presented in the UI alternatives modal with a red box and human-readable elimination reason so the operator can manually override if necessary.

| Filter | Description | Rejection Reason Example |
|--------|-------------|--------------------------|
| `filter_by_exclusive_lab_dynamic` | Checks if diagnostician is bound exclusively to a specific lab | `Αποκλειστικό εργαστήριο (ΚΟΛΙΑΤΣΟΥ)` |
| `filter_by_availability` | Verifies diagnostician is active, working today, and not on leave | `Σε άδεια` / `Εκτός προγράμματος` |
| `filter_by_capacity` | Checks if current daily count reached the weekday quota limit | `Έχει συμπληρώσει το ημερήσιο όριο (15/15)` |
| `filter_by_modality_quotas_dynamic` | Checks specific CT or MRI daily max quota limit | `Έχει συμπληρώσει το όριο (20 CT/ημέρα)` |
| `filter_by_modality` | Checks capability flags (`can_ct`, `can_mri`) against exam category | `Δεν αναλαμβάνει CT` |
| `filter_by_skills_hard` | Eliminates candidate if explicit skill record exists with `is_preferred = 0` | `Δεν διαγιγνώσκει τον συγκεκριμένο κωδικό` |

#### Stage 2: Weighted Scoring
Each candidate passing Stage 1 receives a normalized score (0.0 to 1.0) calculated from dynamic weights loaded from `system_settings`:

$$\text{Total Score} = \sum (\text{Factor Raw Score} \times \text{Factor Weight})$$

| Scoring Factor | Dynamic Key | Default Weight | Description |
|----------------|-------------|----------------|-------------|
| **Patient History** | `pts_history` | `0.35` | Continuity of care (diagnostician reviewed patient's past exams) |
| **Doctor Partnership** | `pts_partnership` | `0.20` | Preferred diagnostician for the issuing doctor |
| **Skills Bonus** | `pts_skills_pref` | `0.20` | Specialization preference (`1.0` preferred, `0.5` neutral, `0.3` no data) |
| **Lab Preference** | `pts_lab_pref` | `0.15` | Matches diagnostician's preferred facility/laboratory |
| **Remaining Capacity** | `pts_capacity` | `0.10` | Ratio of remaining daily quota slots |

#### Stage 3: Near-Tie Load Balancing
To prevent the same top-scoring diagnostician from receiving all sequential recommendations when equally qualified candidates exist, DiagFlow groups candidates within `SCORE_TIE_TOLERANCE` (default `0.05` / 5%) of the top candidate. Within this **near-tie group**, ranking switches to:
1. **Fewest assigned exams today** (plus active session suggestion offset)
2. **Largest daily quota capacity**
3. **Random jitter** (final tie-breaker)

#### Stage 4: Optimization Solver
- **Single Exam Request:** Greedy pick of Rank #1 after load-balancing tie-break.
- **Batch Processing:** Google OR-Tools CP-SAT solver maximizes global compatibility across all pending exams subject to capacity constraints.

---

### 2. Auto-Assignment System

DiagFlow automates routine assignments upon pulling pending exams:
1. **Exclusive Partnerships:** Active doctor-diagnostician exclusive pairs are auto-assigned.
2. **Dynamic Exam Routing Rules:** Configurable routing rules matching specific labs, exam codes, or doctors (e.g. Arthrografies to designated specialists, Spectroscopies, TMJ).
3. **Παμμακάριστος On-Call:** Exams originating from Παμμακάριστος hospital are automatically routed to today's designated on-call diagnostician.

Auto-assigned exams appear directly in the **Assigned** tab with an `AUTO` badge and rule description, ready for secretariat review and Slis push.

---

### 3. Central Database & Multi-Client Architecture

In production, DiagFlow connects directly to a **Central MSSQL Database** over the local hospital network (LAN), integrating seamlessly alongside native Slis tables without table collisions via the `df_*` table prefix. Multiple secretarial and administrative PCs run `DiagFlow.exe` simultaneously, completely synchronized in real time.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                 Central MSSQL Server (e.g. server_hostname/SlisDB)          │
├─────────────────────────────────────────────┬───────────────────────────────┤
│        Native Slis Schema (Operational)     │   DiagFlow Schema (df_* prefix)│
├─────────────────────────────────────────────┼───────────────────────────────┤
│ • exammore (medical exams)                  │ • df_diagnosticians & skills  │
│ • SP: getExamsListForPeriod_V1              │ • df_partnerships & df_doctors│
│ • SP: getWardDoctors                        │ • df_availability (leaves)    │
│ • SP: getdiagnosticsList                    │ • df_local_assignments (staged│
│                                             │ • df_assignment_log (audit)   │
│                                             │ • df_pamakristos_schedule     │
│                                             │ • df_exam_routing_rules       │
│                                             │ • df_exclusive_lab_rules      │
│                                             │ • df_modality_quotas          │
│                                             │ • df_system_settings & admin  │
└─────────────────────────────────────────────┴───────────────────────────────┘
                                ▲                      ▲
                  LAN (pyodbc)  │                      │  LAN (pyodbc)
            ┌───────────────────┴──┐                ┌──┴───────────────────┐
            │  Client PC 1 (Admin) │                │ Client PC 2 (Secr.)  │
            │     DiagFlow.exe     │                │     DiagFlow.exe     │
            └──────────────────────┘                └──────────────────────┘
```

#### Multi-User Real-Time Sync Highlights:
- **Zero Local Caching Overhead:** Direct queries against the central database eliminate out-of-sync local SQLite copies.
- **Shared Staged Assignments (`df_local_assignments`):** When Operator A assigns an exam, all operators see the updated quotas and unassigned pools immediately.
- **Instant Admin Propagation:** Quota, leave, and partnership updates in `admin.html` immediately take effect on all client PCs.
- **Central DDL & Seeding Scripts:** `db/create_central_tables.sql` (schema DDL) and `db/seed_central_tables.sql` (data initializer).

---

### 4. Two-Way Slis Sync Service

- **Pull (On-Demand / Startup):** When `USE_MOCK_SLIS_DB=false`, executes stored procedure `EXEC getExamsListForPeriod_V1 'YYYY-MM-DD', 'YYYY-MM-DD'` on the Slis MSSQL DB to pull unassigned exams (`DIAGNOSTIS IS NULL`) for the last 3 days directly in memory. In mock mode, reads from `mock_slis.db`. Runs Stage 0 auto-assignment rules, stages into `df_local_assignments`, and populates the Secretariat pending table.
- **Doctor Sync (Startup / Daily 3 AM Cron):** When `USE_MOCK_SLIS_DB=false`, executes stored procedure `EXEC getWardDoctors` on launch and via daily APScheduler cron to sync new issuing/ward doctors (`CODE`, `DOCNAME`) into `df_doctors` (or local `doctors` table in dev, inserting new IDs only).
- **Diagnostician Sync (Admin Panel 'Refresh'):** When `USE_MOCK_SLIS_DB=false`, executes stored procedure `EXEC getdiagnosticsList` when the admin clicks "Refresh" to sync new diagnosticians (`PERSONELID`, `DOCNAME`) into `df_diagnosticians` (or local `diagnosticians` table in dev, inserting new IDs only).
- **Push (Manual Trigger):** Pushes confirmed local assignments (`POST /api/slis/push-all` or `/api/slis/push-selected`) directly to Slis (`UPDATE exammore SET diagnostisid=? WHERE exammoreid=?`), recording the audit log in `df_assignment_log` and clearing `df_local_assignments`.

---

## 💻 User Interfaces

### Secretariat Review Dashboard (`index.html`)
- **1. Pending Tab:** Unassigned exams table, order grouping, automated suggestions, score breakdown tooltips, alternatives modal, and bulk assignments.
- **2. Assigned Tab:** Assigned exams, Slis sync status badges ("✅ Synced", "⚠️ Pending Slis Update"), manual/bulk push to Slis, and auto-routing rule badges.
- **3. Dashboard Tab:** Real-time diagnostician daily quotas, completed diagnoses, remaining capacity, and CT/MRI breakdown.
- **4. Slis Search Tab:** Live Slis DB search form with field-specific domain icons (`📋 Order ID`, `👤 Patient`, `🩺 Doctor`, `👨‍⚕️ Diagnostician`, `📆 Date Range`), clean exam titles, colored modality pills (`MRI`, `CT`, `MRA`), Slis status tracking ("⚠️ Pending Slis Update"), and interactive re-assignment popover with real-time hard skill/quota/availability checks and available-first sorting.

> 🔒 **Multi-exam Order Alignment Lock:** All sub-exams belonging to the same Order ID (`extracode`) are automatically locked to the highest-scoring eligible diagnostician, guaranteeing 100% diagnostic consistency across order sub-exams.

### Admin Control Panel (`admin.html`)
- **Security:** Token-based admin authentication (`X-Admin-Token`) with bcrypt password hashing (cost factor 12), IP-based rate limiting (5 attempts/60s with 1.0s throttling delay), and interactive credential management modal.
- **Diagnostician Management:** Quota limits (Monday–Sunday), CT/MRI capabilities, and preferred lab settings.
- **Skills Matrix:** Per-diagnostician exam code specialization and proficiency mappings.
- **Partnerships:** Doctor-diagnostician pairings and exclusivity flags.
- **Dynamic Routing Rules:** Flexible rules routing specific exam codes and labs to targeted diagnosticians.
- **Exclusive Lab Rules & Modality Quotas:** Strict lab binding and daily CT/MRI limits.
- **System Settings:** Real-time adjustment of scoring factor weights (`pts_partnership`, `pts_history`, etc.).
- **Παμμακάριστος Weekly Schedule:** Interactive weekly rotation manager and single-day override calendar.

---

## 🛠️ Prerequisites

- **Python 3.11+**
- **Microsoft ODBC Driver 17 for SQL Server** (required for production MSSQL Slis database connection)
- **Microsoft Edge WebView2 Runtime** (pre-installed on Windows 11 / modern Windows 10, required for standalone desktop app)
- **Web Browser** (Edge, Chrome, Firefox, or Safari) for web server mode
- **SQLite 3** *(embedded in standard Python library; used strictly for local offline testing/development with mock data)*
- **Windows 10/11** (for standalone `.exe` build & execution)

---

## 🚀 Installation & Localhost Running Guide

### 💻 Running DiagFlow Locally on Localhost

This section provides complete, step-by-step instructions for running DiagFlow on `localhost` (development & testing mode), detailing all required files, initialization commands, server options, and verification steps.

#### 1. Prerequisites & System Requirements
* **Python 3.10+** (Python 3.11, 3.12, 3.13, 3.14 fully supported)
* **Git** (for repository cloning)
* **Web Browser** (Edge, Chrome, Firefox, or Safari) or **Edge WebView2** (for desktop GUI mode)

#### 2. Required Files & Key Components
Before launching, verify that the following core files exist in the workspace:
* `requirements.txt` — Python package dependencies
* `.env.example` — Template environment configuration
* `src/diagflow/main.py` — FastAPI web server entrypoint & REST API routes
* `src/diagflow/launcher.py` — Native desktop GUI launcher (`pywebview`)
* `db/create_diagflow_db.py` — Seeder script for application config database (`db/diagflow.db`)
* `db/seed_mock_db.py` — Seeder script for mock SLIS exam database (`db/mock_slis.db`)
* `db/seed_templates.py` — Seeder script for sanitized template copies (`db/templates/`)
* `frontend/` — Secretariat dashboard & admin UI HTML/JS/CSS assets

#### 3. Step-by-Step Terminal Commands

##### Step 1: Clone Repository & Create Virtual Environment
```powershell
# Clone the repository
git clone https://github.com/Georgekon4002/diagflow.git
cd diagflow

# Create a Python virtual environment
python -m venv .venv

# Activate the virtual environment
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Windows (Command Prompt):
.\.venv\Scripts\activate.bat
# Linux / macOS:
source .venv/bin/activate
```

##### Step 2: Install Package Dependencies
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

##### Step 3: Configure Environment File (`.env`)
```powershell
# Copy environment configuration template
copy .env.example .env    # Windows CMD / PowerShell
# cp .env.example .env     # Linux / macOS
```

Configure `.env` settings according to your environment:
```ini
# --- Database Configuration ---
USE_MOCK_SLIS_DB=true
MOCK_SLIS_DB_PATH=db/mock_slis.db
SLIS_DB_CONNECTION_STRING=mssql+pyodbc://diagflow_user:SecurePassword123!@server_hostname/SlisDB?driver=ODBC+Driver+17+for+SQL+Server
CONFIG_DB_CONNECTION_STRING=sqlite:///db/diagflow.db

# --- Rule Engine Weights ---
WEIGHT_PARTNERSHIP=0.35
WEIGHT_PATIENT_HISTORY=0.20
WEIGHT_SKILLS=0.20
WEIGHT_LAB=0.15
WEIGHT_CAPACITY=0.10

# --- Server Settings ---
APP_HOST=127.0.0.1
APP_PORT=8000
LOG_LEVEL=INFO
```

##### Step 4: Initialize Databases & Seed Mock Exam Data
```powershell
# Set PYTHONPATH to include src/
$env:PYTHONPATH="src"     # Windows PowerShell
# set PYTHONPATH=src      # Windows CMD
# export PYTHONPATH=src   # Linux / macOS

# 1. Create & seed application config DB (db/diagflow.db)
python db/create_diagflow_db.py

# 2. Create & seed mock SLIS exam DB (db/mock_slis.db)
python db/seed_mock_db.py

# 3. (Optional) Create & refresh generic demo template databases (db/templates/*)
python db/seed_templates.py
```
> [!NOTE]
> **Privacy & Security Note:** Raw database SQL dumps containing real medical facility data (`db/init_diagflow.sql` and `db/init_mock_slis.sql`) are explicitly ignored by `.gitignore` so sensitive data is never committed to public repositories. The seeder scripts (`create_diagflow_db.py` & `seed_mock_db.py`) automatically detect if raw dumps are missing and fall back to the sanitized, generic template data in `db/templates/`.

##### Step 5: Launch Application

###### Option A: Fast Development Web Server (Uvicorn + Hot Reloading)
Runs FastAPI on `localhost` with automatic code reloading:
```powershell
$env:PYTHONPATH="src"
uvicorn diagflow.main:app --reload --host 127.0.0.1 --port 8000
```
Access endpoints in your browser:
* **Secretariat Dashboard:** [http://localhost:8000](http://localhost:8000)
* **Admin Control Panel:** [http://localhost:8000/admin.html](http://localhost:8000/admin.html)
* **Interactive API Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)

###### Option B: Native Desktop Window GUI (pywebview Launcher)
Launches the application inside a native Windows desktop window:
```powershell
$env:PYTHONPATH="src"
python src/diagflow/launcher.py
```

###### Option C: Standalone Executable Build (`DiagFlow.exe`)
Builds and runs a single binary executable:
```powershell
python scripts/build_exe.py
.\dist\DiagFlow.exe
```

##### Step 6: Run Automated Tests
```powershell
$env:PYTHONPATH="src"
python -m pytest
```

---

### Option B: Building & Running Standalone Desktop EXE

DiagFlow can be compiled into a standalone Windows executable (`DiagFlow.exe`) that launches a background server and embeds the UI inside a native desktop app window using `pywebview`.

#### 1. Build Executable

```powershell
# Run the automated PyInstaller build script
python scripts/build_exe.py
```

The script compiles all code, bundles static frontend assets, sets up hidden imports, and outputs the executable to:
```
dist/DiagFlow.exe
```

#### 2. Run Desktop App

Double-click `dist/DiagFlow.exe` or execute from command line:
```powershell
.\dist\DiagFlow.exe
```
The app will automatically launch the FastAPI server on port `8080` in the background and open the Secretariat Dashboard in a native desktop window.

---

### 📦 Deploying to Another PC

#### 1. Deploying Standalone EXE (Production / End-Users):
1. **Download Executable:** Download `DiagFlow.exe` directly from the **[GitHub Releases](https://github.com/Georgekon4002/diagflow/releases)** page of the repository (or copy your built `dist/DiagFlow.exe`).
2. **Configure `.env` File:** Create a `.env` file in the **same directory as `DiagFlow.exe`** with your central MSSQL connection:
   ```ini
   USE_MOCK_SLIS_DB=false
   SLIS_DB_CONNECTION_STRING=mssql+pyodbc://diagflow_user:Password123!@server_hostname/SlisDB?driver=ODBC+Driver+17+for+SQL+Server
   CONFIG_DB_CONNECTION_STRING=mssql+pyodbc://diagflow_user:Password123!@server_hostname/SlisDB?driver=ODBC+Driver+17+for+SQL+Server
   ```
3. **No `db/` Folder Needed in Production:** When connected to the Central MSSQL server, DiagFlow connects directly to the central `df_*` tables and Slis tables over the LAN. **You do NOT need to copy or provide a `db/` folder.**
4. **Launch:** Double-click `DiagFlow.exe`. The application opens immediately in a native full-screen desktop window.

#### 2. Offline / Testing Mode with Mock Data:
* **Automatic `db/` Generation:** When running in mock test mode (`USE_MOCK_SLIS_DB=true` or without an MSSQL connection), **the `db/` folder is automatically created on startup**. The application auto-initializes `mock_slis.db` and `diagflow.db` from embedded, sanitized templates in `db/templates/`.
* **Customizing / Re-seeding Mock Data:** If you want to populate or customize mock exam records for testing, you can execute the seeder scripts:
  ```powershell
  python db/create_diagflow_db.py   # Populates mock diagnosticians, skills, rules
  python db/seed_mock_db.py         # Populates sample pending/assigned CT & MRI exams
  ```

#### 3. Deploying Web Server (For Browser Network Access):
1. Copy the repository source code to the target host PC.
2. Install Python 3.11+ and run `pip install -r requirements.txt`.
3. Set `APP_HOST=0.0.0.0` and `APP_PORT=8000` in `.env`.
4. Run `uvicorn diagflow.main:app --host 0.0.0.0 --port 8000`.
5. Other PCs on the local network can access the dashboard directly via `http://<HOST_PC_IP>:8000`.

---

## 📊 Database Architecture & Schemas

### 1. Central MSSQL Database Schema (`df_*` Tables)

In production, all DiagFlow configuration, business rules, staging state, and audit logs are hosted in the **Central MSSQL Database** under the `df_` table prefix, coexisting seamlessly with native Slis tables without naming conflicts:

| Table | Description | Primary Key | Key Columns |
|-------|-------------|-------------|-------------|
| `df_diagnosticians` | Diagnosticians master list | `id` (INT) | `name`, `active`, `can_ct`, `can_mri`, `quota_monday..sunday`, `preferred_lab_id` |
| `df_diagnostician_skills` | Exam code proficiencies | `id` (INT) | `diagnostician_id`, `exam_code`, `is_preferred` |
| `df_partnerships` | Doctor-diagnostician pairings | `id` (INT) | `issuing_doctor_id`, `preferred_diagnostician_id`, `priority`, `exclusive`, `is_active` |
| `df_availability` | Daily leave & status calendar | `id` (INT) | `diagnostician_id`, `date`, `status`, `is_pamakristos_oncall` |
| `df_doctors` | Doctor catalogue cache | `id` (NVARCHAR) | `name` |
| `df_local_assignments` | Shared staged un-pushed assignments | `exammoreid` (INT) | `diagnostician_id`, `diagnostician_name`, `assigned_at`, `is_auto`, `rule_desc` |
| `df_assignment_log` | Central audit trail history | `exammoreid` (INT) | `diagnostician_id`, `assigned_at`, `modality`, `extracode` |
| `df_pamakristos_schedule` | Standard weekly on-call rotation | `weekday` (INT) | `diagnostician_id` (0=Mon .. 6=Sun) |
| `df_exam_routing_rules` | Dynamic exam auto-assign rules | `id` (INT) | `lab_id`, `is_pamakristos`, `exam_codes`, `diagnostician_id`, `description`, `is_active` |
| `df_exclusive_lab_rules` | Strict lab bindings | `id` (INT) | `diagnostician_id`, `lab_id`, `lab_name`, `is_active` |
| `df_modality_quotas` | CT/MRI specific daily limits | `id` (INT) | `diagnostician_id`, `modality`, `max_count`, `is_active` |
| `df_system_settings` | Dynamic scoring factor weights | `key` (NVARCHAR) | `value` (e.g. `pts_partnership`, `pts_history`, `pts_skills_pref`, `pts_lab_pref`, `pts_capacity`) |
| `df_admin_users` | Authenticated admin & IT users | `id` (INT) | `username`, `password_hash` (bcrypt), `role` (`admin`/`it_support`), `is_active` |
| `df_exam_dictionary` | Exam catalog & categories | `code` (NVARCHAR) | `name`, `category` (`CT`/`MRI`/`MRA`) |

### 2. Native Slis Tables & Stored Procedures (MSSQL)

| Object | Type | Description | Key Columns / Parameters |
|--------|------|-------------|--------------------------|
| `exammore` | Table | Operational medical exams | `exammoreid` (PK), `extracode`, `visitid`, `demogid`, `examnumcode`, `visitdate`, `labcodeid`, `wcode`, `diagnostisid` |
| `getExamsListForPeriod_V1` | Stored Proc | Pulls unassigned exams | `@DateFrom`, `@DateTo` (returns unassigned exams for the period) |
| `getWardDoctors` | Stored Proc | Syncs doctors | Returns `CODE`, `DOCNAME` from Slis |
| `getdiagnosticsList` | Stored Proc | Syncs diagnosticians | Returns `PERSONELID`, `DOCNAME` from Slis |

### 3. Mock Test Database (Offline Development Harness)

When running locally with `USE_MOCK_SLIS_DB=true`, DiagFlow uses an auto-generated SQLite test harness mirroring the schema above (`mock_slis.db` for exams and `diagflow.db` for config) to allow offline testing without connecting to the hospital network.

---

## ⚙️ Configuration & Environment Settings

System settings are managed via the `.env` configuration file:

### `.env` Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_MOCK_SLIS_DB` | `false` | When `false`, connects to production Central MSSQL server. Set to `true` for offline testing with mock data. |
| `SLIS_DB_CONNECTION_STRING` | — | MSSQL ODBC connection string for operational Slis database. |
| `CONFIG_DB_CONNECTION_STRING` | — | MSSQL ODBC connection string for DiagFlow `df_*` tables. |
| `MOCK_SLIS_DB_PATH` | `db/mock_slis.db` | Relative path to local SQLite mock database (used only when `USE_MOCK_SLIS_DB=true`). |
| `SCORE_TIE_TOLERANCE` | `0.05` | Score tolerance threshold (5%) for near-tie load balancing. |
| `APP_HOST` | `0.0.0.0` | Host IP interface to bind server. |
| `APP_PORT` | `8080` | Port number for web server. |
| `LOG_LEVEL` | `INFO` | Application logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

---

## 📡 API Reference

All REST API endpoints are prefixed with `/api`. Interactive Swagger documentation is available at `/docs`.

### 🩺 System & Health
- `GET /api/health` — Application health check and environment status.

### 📋 Exams
- `GET /api/exams/pending` — Fetch pending (unassigned) exams from Slis (or mock DB) processed in memory.
- `GET /api/exams/assigned` — Fetch staged local assignments awaiting Slis push (`df_local_assignments`).

### ⚙️ Assignment Engine
- `POST /api/assignments/suggest` — Run 4-stage pipeline and generate assignment suggestion for a single exam.
- `POST /api/assignments/suggest-batch` — High-performance in-memory batch suggestions for all pending exams.
- `POST /api/assignments/confirm` — Confirm suggested assignment and stage to local assignments.
- `POST /api/assignments/override` — Override suggestion with a different diagnostician and log reason.
- `POST /api/assignments/bulk-confirm` — Confirm suggestions for multiple selected exams in bulk.
- `POST /api/assignments/bulk-override` — Override multiple selected exams to a single diagnostician.
- `POST /api/assignments/bulk-eligible-diagnosticians` — Get intersection of available diagnosticians for selected exams.
- `DELETE /api/assignments/{exam_id}` — Remove a locally staged assignment by exam ID (unassign).
- `POST /api/assignments/unassign` — Unassign a single staged assignment and return exam to pending list.
- `POST /api/assignments/bulk-unassign` — Unassign multiple staged assignments in bulk.
- `GET /api/assignments/weights` — Fetch active dynamic scoring factor weights.
- `PUT /api/assignments/weights` — Update scoring factor weights dynamically in runtime and database.

### 🔄 Slis Sync & Search
- `POST /api/slis/pull` — Refresh pending exam data from Slis via `EXEC getExamsListForPeriod_V1` directly in memory.
- `GET /api/slis/status` — Check Slis database connection status and pending push count.
- `POST /api/slis/push-all` — Push ALL confirmed local assignments back to Slis (`UPDATE exammore`), log to `df_assignment_log`, and clear `df_local_assignments`.
- `POST /api/slis/push-selected` — Push selected list of `exammoreid`s back to Slis.
- `POST /api/slis/search` — Search live Slis database by date range, Order ID (`extracode`), Patient Name, Doctor, Diagnostician.
- `POST /api/slis/reassign` — Reassign an already-synced exam directly in Slis (`exammore`) with audit logging.

### 👨‍⚕️ Diagnosticians, Doctors & Dashboard
- `GET /api/diagnosticians` — List active diagnosticians with daily quota progress and CT/MRI modality breakdown.
- `GET /api/doctors` — Search and list doctors with pagination.
- `GET /api/dashboard` — Summary metrics and daily analytics for the secretariat dashboard.
- `GET /api/pamakristos/oncall` — Get today's designated Παμμακάριστος on-call diagnostician.
- `GET /api/pamakristos/schedule` — Get standard weekly Παμμακάριστος on-call rotation schedule.
- `POST /api/pamakristos/oncall` — Set manual on-call diagnostician for a specific date.

### 🔐 Admin Panel (Requires `X-Admin-Token` Header & Active Session)
- `POST /api/admin/auth/login` — Authenticate admin credentials with bcrypt hashing and rate limiting.
- `POST /api/admin/auth/change-credentials` — Update personal admin username and/or password.
- `GET/POST /api/admin/users` — CRUD admin users (with roles `admin` / `it_support`, password reset, active toggle).
- `PUT/DELETE /api/admin/users/{user_id}` — Update user username, password, role, active status or delete user (`it_support`).
- `POST /api/admin/users/{user_id}/reset` — Reset user credentials to default `admin / admin1234` (`it_support`).
- `POST /api/admin/users/{user_id}/toggle` — Toggle active/inactive status of an admin user (`it_support`).
- `GET/POST /api/admin/diagnosticians` — List / create diagnosticians and weekly quotas.
- `PUT/DELETE /api/admin/diagnosticians/{diag_id}` — Update / delete diagnostician record.
- `POST /api/admin/diagnosticians/sync` & `POST /api/admin/sync-diagnosticians` — Trigger manual personnel sync from Slis (`EXEC getdiagnosticsList`).
- `GET/POST/DELETE /api/admin/skills` — CRUD diagnostician exam code specialization and proficiency mappings.
- `PUT/DELETE /api/admin/skills/{skill_id}` — Update / delete diagnostician skill mapping.
- `GET /api/admin/exam-categories` — Fetch all exam dictionary categories and exams for bulk skill assignment.
- `GET/POST/DELETE /api/admin/partnerships` — CRUD doctor partnerships with priority and exclusivity flags.
- `PATCH/DELETE /api/admin/partnerships/{part_id}` — Update / delete doctor partnership.
- `GET/POST/DELETE /api/admin/doctors` — CRUD doctor master records.
- `POST /api/admin/doctors/sync` & `POST /api/admin/sync-doctors` — Trigger manual doctor sync from Slis (`EXEC getWardDoctors`).
- `GET/POST /api/admin/availability` — List / upsert daily availability records and leaves.
- `DELETE /api/admin/availability/{diagnostician_id}/{date}` — Delete daily availability override or leave.
- `GET/POST /api/admin/oncall` — Get / set on-call diagnostician override for a specific date.
- `GET/POST /api/admin/pamakristos/weekly-schedule` — Manage standard weekly on-call schedule.
- `GET/DELETE /api/admin/pamakristos/overrides` & `DELETE /api/admin/pamakristos/overrides/{avail_id}` — Manage manual on-call calendar overrides.
- `GET/POST/PUT/DELETE /api/admin/advanced/exam-routing-rules` — CRUD dynamic exam auto-routing rules.
- `GET/POST/PUT/DELETE /api/admin/exclusive-lab-rules` — CRUD strict lab constraints.
- `GET/POST/PUT/DELETE /api/admin/modality-quotas` — CRUD specific CT/MRI daily limits.

---

## 📁 Project Structure

```
diagflow/
├── README.md                          # Comprehensive project documentation (English)
├── README.el.md                       # Comprehensive project documentation (Greek)
├── USER_GUIDE.md                      # Comprehensive Secretariat & Admin User Guide
├── pyproject.toml                     # Python build configuration & pytest setup
├── requirements.txt                   # Production Python package dependencies
├── .env.example                       # Environment configuration template
├── DiagFlow.spec                      # PyInstaller specification for standalone EXE
│
├── db/                                # Central database schemas & template seeders
│   ├── create_central_tables.sql      # T-SQL DDL script for Central MSSQL df_* tables
│   ├── create_diagflow_db.py          # Seeder script for mock config database
│   ├── seed_mock_db.py                # Seeder script for mock SLIS exams database
│   ├── seed_templates.py              # Template database generator script
│   ├── init.sql                       # Base schema DDL for mock testing
│   ├── table.sql                      # Reference table schema
│   ├── update_slis.sql                # Stored procedure reference scripts
│   └── templates/                     # Embedded sanitized SQLite template databases
│       ├── diagflow.db                # Sanitized config DB template
│       ├── mock_slis.db               # Sanitized mock exam DB template
│       ├── init_diagflow.sql          # Sanitized config SQL seed template
│       └── init_mock_slis.sql         # Sanitized mock exam SQL seed template
│
├── frontend/                          # Clean Vanilla HTML5 / CSS3 / JS UI Layer
│   ├── index.html                     # Secretariat review dashboard (4 tabs)
│   ├── admin.html                     # Admin control panel
│   ├── css/
│   │   └── styles.css                 # Unified stylesheet & design system
│   ├── js/
│   │   ├── app.js                     # Secretariat dashboard logic & keyboard engine
│   │   └── admin.js                   # Admin panel interactive management logic
│   └── media/
│       └── logos/                     # Application logos and iconography
│
├── guides/                            # Standalone HTML Guide Exports
│   └── *.html                         # Self-contained offline HTML documentation
│
├── src/diagflow/                      # Core Python Application Package
│   ├── __init__.py                    # Package metadata & version
│   ├── main.py                        # FastAPI entrypoint, router mounts & lifespan
│   ├── config.py                      # Pydantic Settings & environment loader
│   ├── launcher.py                    # Standalone desktop window launcher (pywebview)
│   │
│   ├── api/                           # REST API Layer
│   │   ├── routes.py                  # API endpoints definition
│   │   ├── schemas.py                 # Pydantic request & response models
│   │   └── dependencies.py            # FastAPI dependency injection providers
│   │
│   ├── db/                            # Data Access Layer
│   │   ├── diagflow_db.py             # Database adapter & CRUD operations (MSSQL / SQLite)
│   │   ├── engines.py                 # SQLAlchemy engine & session factory
│   │   ├── models.py                  # Config ORM models
│   │   └── slis_models.py             # Slis ORM models
│   │
│   ├── engine/                        # Rule Engine & Optimization Core
│   │   ├── pipeline.py                # 4-stage pipeline orchestrator
│   │   ├── filters.py                 # Hard constraints & eligibility filters
│   │   ├── scoring.py                 # Weighted multi-factor scoring & near-tie balancer
│   │   ├── solver.py                  # Google OR-Tools CP-SAT solver & greedy fallback
│   │   └── rules.py                   # Rule definitions & registry
│   │
│   ├── services/                      # Business Logic Services
│   │   ├── assignment.py              # Assignment lifecycle, auto-assign & audit log
│   │   ├── diagnostician.py           # Candidate loading, batch caching & enrichment
│   │   ├── pamakristos.py             # Παμμακάριστος on-call rotation manager
│   │   └── slis_sync.py               # Slis pull/push sync & APScheduler daily cron
│   │
│   └── utils/                         # Utilities
│       └── logging.py                 # Structured logging configuration
│
├── puml/                              # PlantUML Architecture & Design Diagrams
│   ├── architecture.puml              # High-level system architecture diagram
│   ├── assignment_sequence.puml       # End-to-end suggest → push sequence diagram
│   ├── class_api.puml                 # API & Launcher class diagram
│   ├── data_api.puml                  # Data access & engine layer class diagram
│   ├── data_model.puml                # Data model overview diagram
│   ├── er_diagram.puml                # Entity-Relationship diagram
│   └── rule_engine_flow.puml          # 4-Stage Rule Engine activity flow diagram
│
├── scripts/                           # Build & Maintenance Scripts
│   ├── build_exe.py                   # Automated PyInstaller Windows EXE builder
│   ├── convert_md_to_html.py          # Markdown to standalone HTML converter
│   └── data_quality_audit.py          # Data quality analysis script
│
├── tests/                             # Automated Test Suite (Pytest)
│   ├── conftest.py                    # Test fixtures & database harness
│   ├── test_admin_auth.py             # Admin auth, bcrypt security & rate limit tests
│   ├── test_auto_init_db.py           # Auto-initialization test suite
│   ├── test_autoassign.py             # Auto-assignment logic unit tests
│   ├── test_filters.py                # Hard filter unit tests
│   ├── test_multi_exam_order.py       # Multi-exam order consistency lock tests
│   ├── test_optimistic_locking.py     # Optimistic locking & concurrent update tests
│   ├── test_pipeline.py               # Pipeline integration tests
│   ├── test_scoring.py                # Weighted scoring & near-tie balance tests
│   └── test_skills_fix.py             # Skill preference & elimination tests
│
└── media/                             # Application Media & Screenshots
    ├── logos/                         # Application logos and brand assets
    └── screenshots/                   # Application screenshots
```

---

## 📐 PlantUML Architecture Diagrams

All PlantUML diagram source files are maintained in the [`puml/`](puml/) directory. You can render them using any PlantUML viewer or the [PlantUML Online Server](https://www.plantuml.com/plantuml/uml/).

| Diagram | Source File | Description |
|---------|-------------|-------------|
| **System Architecture** | [`architecture.puml`](puml/architecture.puml) | Component diagram including FastAPI, Data Layer, Databases, pywebview Launcher, and PyInstaller build pipeline. |
| **Assignment Sequence** | [`assignment_sequence.puml`](puml/assignment_sequence.puml) | End-to-end sequence for startup auto-assignments, fetching pending exams, pipeline execution, operator confirmation, and Slis push. |
| **Class Diagram: API & Launcher** | [`class_api.puml`](puml/class_api.puml) | Structural class diagram of routes, request/response models, services, settings, and app launcher. |
| **Class Diagram: Data & Engine** | [`data_api.puml`](puml/data_api.puml) | Class diagram of data access functions, candidate structures, hard filter functions, scoring components, and solver wrappers. |
| **Data Model Overview** | [`data_model.puml`](puml/data_model.puml) | Overview of entities and cross-database references across `diagflow.db` and `mock_slis.db`. |
| **Entity-Relationship Diagram** | [`er_diagram.puml`](puml/er_diagram.puml) | Detailed ER diagram with full column attributes, primary keys, foreign keys, unique constraints, and table relationships. |
| **Rule Engine Pipeline Flow** | [`rule_engine_flow.puml`](puml/rule_engine_flow.puml) | Activity diagram showing decision paths through Stage 0 auto-assignment, Stage 1 hard filters, Stage 2 scoring, Stage 3 near-tie load balancing, and Stage 4 solver. |

---

## 📸 Screenshots

### 🖥️ Secretariat Dashboard

<div align="center">

| Homescreen (Pending Tab - Bright Mode) | Homescreen (Pending Tab - Dark Mode) |
|:---:|:---:|
| ![Homescreen 1](media/screenshots/homescreen1.png) | ![Homescreen 2](media/screenshots/homescreen2.png) |

| Dashboard Overview & Modality Distribution | Auto-Assignment (Assigned Tab) |
|:---:|:---:|
| ![Dashboard](media/screenshots/dashboard_blurred.png) | ![Auto-Assign](media/screenshots/auto-assign.png) |

| Search & Dynamic Filtering | Multiple Row Selection & Floating Action Bar |
|:---:|:---:|
| ![Filtering](media/screenshots/filtering.png) | ![Multiple Select](media/screenshots/multipleselect.png) |

| Slis Direct Search & Reassignment (4th Tab) | Slis Reassignment Confirmation |
|:---:|:---:|
| ![Slis Search & Reassign](media/screenshots/changediagnostician.png) | ![Slis Reassignment Success](media/screenshots/changeddiagnostician.png) |

</div>

---

### 🧮 Rule Engine & Scoring

<div align="center">

| Alternatives & Eligibility Modal | Scoring System Breakdown |
|:---:|:---:|
| ![Alternatives](media/screenshots/alternatives_blurred.png) | ![Scoring System](media/screenshots/scoring-system.png) |

| Detailed Score Factor Breakdown | Assignment Decision Flow Diagram |
|:---:|:---:|
| ![Scoring](media/screenshots/scoring.png) | ![Flow](media/screenshots/flow.png) |

</div>

---

### 🔐 Admin Control Panel

<div align="center">

| Diagnosticians Management & Quotas | Availability Calendar & Leaves |
|:---:|:---:|
| ![Admin Diagnosticians](media/screenshots/admin_diagnosticians.png) | ![Admin Availability](media/screenshots/admin_availability.png) |

| Capacity & Modality Specialization Matrix | Skills Preferences & Exclusions Matrix |
|:---:|:---:|
| ![Admin Skills 1](media/screenshots/admin_skills1_blurred.png) | ![Admin Skills 2](media/screenshots/admin_skills2.png) |

| Skills Matrix Management & Category Filtering | Doctor Partnerships & Exclusivities |
|:---:|:---:|
| ![Admin Skills 3](media/screenshots/admin_skills3.png) | ![Admin Partners](media/screenshots/admin_partners.png) |

| Παμμακάριστος Schedule & Overrides | Exam Catalog & Anatomical Groups |
|:---:|:---:|
| ![Admin Pammakaristos](media/screenshots/admin_pammakaristos.png) | ![Admin Exams 1](media/screenshots/admin_exams1.png) |

| Dynamic Exam Auto-Routing Rules | Exclusive Labs & Modality Quotas |
|:---:|:---:|
| ![Admin Advanced 1](media/screenshots/admin_advanced1.png) | ![Admin Advanced 2](media/screenshots/admin_advanced2.png) |

| Dynamic Scoring Factor Weights Editor | |
|:---:|:---:|
| ![Admin Advanced 3](media/screenshots/admin_advanced3.png) | |

</div>

---

## 📄 License

Internal proprietary software — **Kosmoiatriki © 2026**. All rights reserved.

---

<div align="center">
  <img src="media/logos/logo_multiple.png" alt="DiagFlow Logo" height="50" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="media/logos/textbox.png" alt="DiagFlow Textbox" height="50" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="media/logos/logo_transparent_crop.png" alt="DiagFlow Transparent Logo" height="50" />
</div>
