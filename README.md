<div align="center">
  <img src="media/full_logo_multiple.png" alt="DiagFlow Logo" width="300" />
</div>

# 🏥 DiagFlow — Automated CT/MRI Report Assignment Engine

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/Database-SQLite%20%2F%20MSSQL-003B57.svg)](https://www.sqlite.org/)
[![OR-Tools](https://img.shields.io/badge/Optimization-Google%20OR--Tools-4285F4.svg)](https://developers.google.com/optimization)
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
| 🧮 **Optimization** | **Google OR-Tools CP-SAT** | Global constraint solver for batch assignments, maximizing total score while enforcing daily capacity & modality quotas. |
| ⚖️ **Load Balancing** | **Near-Tie Rotation** | Candidates within a configurable score tolerance (default 5%) are ranked by workload, preventing individual burnout. |
| 🔄 **Session Offset** | **Real-Time Workload Tracking** | Tracks uncommitted suggestions within an active session so sequential proposals distribute workload evenly before confirmation. |
| ⚡ **Auto-Assignments** | **Dynamic Routing Rules** | Automatically assigns exclusive doctor partnerships, lab-specific exam codes (e.g. Arthrografies, TMJ, Spectroscopies), and Παμμακάριστος on-call rotation. |
| 🛡️ **Hard Constraints** | **Dynamic Quotas & Labs** | Enforces leave calendars, weekday quotas, modality limits (CT/MRI max counts), exclusive lab assignments, and skill proficiencies. |
| 🔄 **Slis Synchronization** | **Two-Way Integration** | Pulls unassigned exams from Slis (past 3 days), pushes confirmed local assignments back, and runs daily 3 AM background master data syncs via APScheduler. |
| 🖥️ **Secretariat Dashboard** | **Tabbed Review Interface** | `index.html` dashboard with pending/assigned tabs, instant suggestions, rule breakdowns, alternative candidate modals, bulk confirm/override, and Slis push. |
| 🔐 **Admin Panel** | **Configuration Management** | Authenticated `admin.html` interface for managing diagnosticians, skills, doctor partnerships, availability calendars, dynamic routing rules, modality quotas, and scoring weights. |
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
                      │  │ diagflow.db (SQLite Config State)│  │
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
| **Doctor Partnership** | `pts_partnership` | `0.35` | Preferred diagnostician for the issuing doctor |
| **Patient History** | `pts_history` | `0.20` | Continuity of care (diagnostician reviewed patient's past exams) |
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

### 3. Dual-Database Architecture

DiagFlow isolates operational Slis exam data from application configuration using two separate databases:

```
┌────────────────────────────────────────┐     ┌────────────────────────────────────────┐
│   mock_slis.db / Slis MSSQL (Production)│     │         diagflow.db (SQLite)           │
├────────────────────────────────────────┤     ├────────────────────────────────────────┤
│ • slis_exams                           │     │ • diagnosticians & skills              │
│ • exam_categories                      │     │ • partnerships & doctors               │
│ • diagnosticians (Slis Personnel)      │     │ • availability calendar                │
│ • doctors (Slis Doctors)               │     │ • local_assignments & assignment_log   │
│                                        │     │ • pamakristos_schedule                 │
│                                        │     │ • exam_routing_rules & exclusive_labs  │
│                                        │     │ • modality_quotas & system_settings    │
└────────────────────────────────────────┘     └────────────────────────────────────────┘
```

---

### 4. Two-Way Slis Sync Service

- **Pull (On-Demand / Startup):** Queries unassigned exams from the last 3 days from Slis (`diagnostis IS NULL`), runs Stage 0 auto-assignment rules, and populates the Secretariat pending table.
- **Push (Manual Trigger):** Pushes confirmed local assignments (`POST /api/slis/push-all` or `/api/slis/push-selected`) directly to Slis (`slis_exams`), recording the sync timestamp.
- **Daily Master Data Cron:** APScheduler automatically triggers a background sync every day at **3:00 AM** to sync Personnel and Doctor master tables from Slis into `diagflow.db`.

---

## 💻 User Interfaces

### Secretariat Review Dashboard (`index.html`)
- **Pending Tab:** Real-time exam table, single-click suggestion generation, visual score breakdown tooltips, alternatives modal with color-coded elimination reasons, and bulk confirm/override actions.
- **Assigned Tab:** Overview of pending Slis pushes, rule tags, auto-assignment badges, and one-click "Send to Slis" synchronization.

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
- **SQLite 3** (embedded in Python, no separate installation required)
- **ODBC Driver 17 for SQL Server** (required for production MSSQL Slis connection)
- **Web Browser** (Chrome, Edge, Firefox, or Safari) for Web mode
- **Windows 10/11** (for standalone `.exe` build)

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
SLIS_DB_CONNECTION_STRING=mssql+pyodbc://diagflow_user:SecurePassword123!@192.168.1.100/SlisDB?driver=ODBC+Driver+17+for+SQL+Server
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

To deploy DiagFlow onto another machine:

#### Deploying Standalone EXE (Easiest for End-Users):
1. Copy the `dist/DiagFlow.exe` file to the target machine.
2. Ensure the `db/` folder containing `diagflow.db` and `mock_slis.db` (or `.env` for production MSSQL) is located in the same directory as `DiagFlow.exe`.
3. Double-click `DiagFlow.exe` to run.

#### Deploying Web Server (For Network Access):
1. Copy the full `diagflow` directory to the target PC.
2. Install Python 3.11 and run `pip install -r requirements.txt`.
3. Set `APP_HOST=0.0.0.0` in `.env`.
4. Run `uvicorn src.diagflow.main:app --host 0.0.0.0 --port 8000`.
5. Other PCs on the local network can access the dashboard via `http://<TARGET_PC_IP>:8000`.

---

## 📊 Database Architecture & Schemas

### `diagflow.db` (Application Config & State)

| Table | Description | Primary Key | Key Columns |
|-------|-------------|-------------|-------------|
| `diagnosticians` | Personnel master list | `id` (INT) | `name`, `active`, `can_ct`, `can_mri`, `quota_monday..sunday`, `preferred_lab_id` |
| `diagnostician_skills` | Exam code proficiencies | `id` (INT) | `diagnostician_id`, `exam_code`, `is_preferred` |
| `partnerships` | Doctor-diagnostician pairings | `id` (INT) | `issuing_doctor_id`, `preferred_diagnostician_id`, `exclusive`, `is_active` |
| `availability` | Daily leave & status calendar | `id` (INT) | `diagnostician_id`, `date`, `status`, `is_pamakristos_oncall` |
| `doctors` | Doctor catalogue | `id` (TEXT) | `name`, `specialty` |
| `local_assignments` | Local un-pushed assignments | `exammoreid` (INT) | `diagnostician_id`, `diagnostician_name`, `assigned_at`, `is_auto`, `rule_desc` |
| `assignment_log` | Audit trail history | `exammoreid` (INT) | `diagnostician_id`, `assigned_at`, `modality`, `extracode` |
| `pamakristos_schedule` | Weekly on-call rotation | `weekday` (INT) | `diagnostician_id` (0=Mon .. 6=Sun) |
| `exam_routing_rules` | Dynamic exam auto-assign rules | `id` (INT) | `lab_id`, `is_pamakristos`, `exam_codes`, `diagnostician_id`, `description`, `is_active` |
| `exclusive_lab_rules` | Strict lab bindings | `id` (INT) | `diagnostician_id`, `lab_id`, `lab_name`, `is_active` |
| `modality_quotas` | CT/MRI specific daily limits | `id` (INT) | `diagnostician_id`, `modality`, `max_count`, `is_active` |
| `system_settings` | Dynamic scoring factor weights | `key` (TEXT) | `value` (e.g. `pts_partnership`, `pts_history`, `pts_lab_pref`) |

### `mock_slis.db` / Slis MSSQL (Exam Data Mirror)

| Table | Description | Primary Key | Key Columns |
|-------|-------------|-------------|-------------|
| `slis_exams` | Pending & assigned exams | `exammoreid` (INT) | `extracode`, `visitid`, `demogid`, `examnumcode`, `visitdate`, `labcodeid`, `wcode`, `diagnostis`, `slis_synced_at` |
| `exam_categories` | Exam code lookup catalogue | `examnumcode` (INT) | `name`, `category` (`CT`, `MRI`, `MRA`) |
| `diagnosticians` | Slis personnel reference | `PERSONELID` (INT) | `DOCNAME` |
| `doctors` | Slis doctor reference | `CODE` (INT) | `DOCNAME` |

---

## ⚙️ Configuration & Environment Settings

System settings are managed via `.env` file and `system_settings` table in `diagflow.db`:

### `.env` File Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_MOCK_SLIS_DB` | `true` | When `true`, reads/writes to local SQLite `mock_slis.db`. Set to `false` for MSSQL production. |
| `MOCK_SLIS_DB_PATH` | `db/mock_slis.db` | Relative path to SQLite mock database. |
| `SLIS_DB_CONNECTION_STRING` | — | MSSQL ODBC connection string for production Slis access. |
| `CONFIG_DB_CONNECTION_STRING` | — | MSSQL ODBC connection string for DiagFlow config tables (if hosted in MSSQL). |
| `SCORE_TIE_TOLERANCE` | `0.05` | Score tolerance threshold (5%) for near-tie load balancing. |
| `APP_HOST` | `0.0.0.0` | Host IP interface to bind server. |
| `APP_PORT` | `8000` | Port number for Web application server. |
| `LOG_LEVEL` | `DEBUG` | Application logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

---

## 📡 API Reference

All REST API endpoints are prefixed with `/api`. Interactive Swagger documentation is available at `/docs`.

### 📋 Exams
- `GET /api/exams/pending` — Fetch pending (unassigned) exams from Slis / mock DB.
- `GET /api/exams/assigned` — Fetch locally assigned exams awaiting Slis push.

### ⚙️ Assignment Engine
- `POST /api/assignments/suggest` — Run 4-stage pipeline and generate assignment suggestion for an exam.
- `POST /api/assignments/confirm` — Confirm suggested assignment and save to local assignments.
- `POST /api/assignments/override` — Override suggestion with a different diagnostician and log reason.
- `POST /api/assignments/bulk-confirm` — Confirm suggestions for multiple exams in bulk.
- `POST /api/assignments/bulk-override` — Override multiple exams to a single diagnostician.

### 🔄 Slis Sync
- `POST /api/slis/pull` — Refresh pending exam data from Slis / mock DB.
- `POST /api/slis/push-all` — Push ALL confirmed local assignments back to Slis.
- `POST /api/slis/push-selected` — Push selected list of `exammoreid`s back to Slis.

### 👨‍⚕️ Diagnosticians & Schedule
- `GET /api/diagnosticians` — List active diagnosticians with current daily workloads.
- `GET /api/pamakristos/oncall` — Get today's Παμμακάριστος on-call diagnostician.
- `GET /api/pamakristos/schedule` — Get weekly Παμμακάριστος on-call rotation schedule.
- `POST /api/pamakristos/oncall` — Set manual on-call diagnostician for a specific date.

### 🔐 Admin Panel (Requires `X-Admin-Token` Header)
- `POST /api/admin/auth/login` — Authenticate admin credentials (`admin` / `admin1234`).
- `POST /api/admin/auth/change-credentials` — Update admin username and/or password (stored as bcrypt hash).
- `GET/POST /api/admin/diagnosticians` — List / create diagnosticians.
- `PUT/DELETE /api/admin/diagnosticians/{id}` — Update / delete diagnostician record.
- `GET/POST/DELETE /api/admin/partnerships` — CRUD doctor partnerships.
- `GET/POST/DELETE /api/admin/doctors` — CRUD doctor master records.
- `GET/POST /api/admin/availability` — List / set daily availability and leave.
- `GET/POST/DELETE /api/admin/skills` — CRUD diagnostician skill proficiencies.
- `GET/POST/DELETE /api/admin/exam-routing-rules` — CRUD dynamic exam auto-routing rules.
- `GET/POST/DELETE /api/admin/exclusive-lab-rules` — CRUD exclusive lab constraints.
- `GET/POST/DELETE /api/admin/modality-quotas` — CRUD specific CT/MRI daily limits.
- `GET/POST /api/admin/system-settings` — Fetch / update scoring factor weights.
- `POST /api/admin/sync-diagnosticians` — Trigger manual personnel sync from Slis.
- `POST /api/admin/sync-doctors` — Trigger manual doctor sync from Slis.

---

## 📁 Project Structure

```
diagflow/
├── README.md                          # Comprehensive project documentation
├── pyproject.toml                     # Python build configuration & dependencies
├── requirements.txt                   # Production dependencies
├── .env.example                       # Environment variable template
├── DiagFlow.spec                      # PyInstaller specification for EXE build
│
├── db/                                # Database schemas, initialization & seeds
│   ├── diagflow.db                    # DiagFlow config & state database (SQLite)
│   ├── mock_slis.db                   # Mock Slis exam database (SQLite)
│   ├── init.sql                       # Base schema for mock_slis.db
│   ├── init_diagflow.sql              # Schema & seed data for diagflow.db
│   ├── init_mock_slis.sql             # Comprehensive seed data for mock_slis.db
│   ├── create_diagflow_db.py          # Database creation utility script
│   └── seed_mock_db.py                # Database seeding utility script
│
├── src/diagflow/                      # Core Python application package
│   ├── __init__.py                    # Package metadata & version
│   ├── main.py                        # FastAPI application entrypoint & lifespan
│   ├── config.py                      # Application settings & environment loader
│   ├── launcher.py                    # Standalone EXE launcher (pywebview)
│   │
│   ├── api/                           # REST API layer
│   │   ├── routes.py                  # API endpoints definition
│   │   ├── schemas.py                 # Pydantic request & response models
│   │   └── dependencies.py            # FastAPI dependency injection providers
│   │
│   ├── db/                            # Data access layer
│   │   ├── diagflow_db.py             # Raw SQLite CRUD operations for diagflow.db
│   │   ├── engines.py                 # Dual SQLAlchemy engine factory (production MSSQL)
│   │   ├── models.py                  # Config ORM reference models
│   │   └── slis_models.py             # Slis ORM reference models
│   │
│   ├── engine/                        # Rule engine pipeline
│   │   ├── pipeline.py                # Pipeline orchestrator (Stages 0–4)
│   │   ├── filters.py                 # Hard filter implementations & dynamic rules
│   │   ├── scoring.py                 # Multi-factor weighted scoring & load balancing
│   │   ├── solver.py                  # OR-Tools CP-SAT batch solver & greedy fallback
│   │   └── rules.py                   # Rule definitions & registry
│   │
│   ├── services/                      # Core business logic services
│   │   ├── assignment.py              # Assignment lifecycle, auto-assign & audit log
│   │   ├── diagnostician.py           # Candidate enrichment & loading
│   │   ├── pamakristos.py             # Παμμακάριστος on-call rotation manager
│   │   └── slis_sync.py               # Slis pull/push sync & APScheduler daily cron
│   │
│   └── utils/                         # Utilities
│       └── logging.py                 # Structlog configuration
│
├── frontend/                          # Web User Interfaces
│   ├── index.html                     # Secretariat review dashboard
│   ├── admin.html                     # Admin control panel
│   ├── css/                           # Stylesheets
│   │   └── styles.css                 # Shared styling
│   ├── js/                            # Client-side JavaScript
│   │   ├── app.js                     # Dashboard interactive logic
│   │   └── admin.js                   # Admin panel interactive logic
│   └── media/                         # Icons & graphic assets
│
├── puml/                              # PlantUML Architecture Diagrams
│   ├── architecture.puml              # High-level system architecture diagram
│   ├── assignment_sequence.puml       # End-to-end suggest → push sequence diagram
│   ├── class_api.puml                 # API & Launcher class diagram
│   ├── data_api.puml                  # Data access & engine layer class diagram
│   ├── data_model.puml                # Data model overview diagram
│   ├── er_diagram.puml                # Entity-Relationship diagram (both DBs)
│   └── rule_engine_flow.puml          # 4-Stage Rule Engine activity flow diagram
│
├── scripts/                           # Utility scripts
│   ├── build_exe.py                   # Automated PyInstaller Windows EXE builder
│   └── data_quality_audit.py          # Data quality analysis script
│
├── tests/                             # Test suite
│   ├── conftest.py                    # Pytest fixtures & setup
│   ├── test_admin_auth.py             # Admin auth, bcrypt security, & SQL whitelisting tests
│   ├── test_filters.py                # Hard filter unit tests
│   ├── test_scoring.py                # Weighted scoring unit tests
│   ├── test_pipeline.py               # Pipeline integration tests
│   └── test_autoassign.py             # Auto-assignment logic unit tests
│
└── docs/                              # Project reference documentation & exports
    ├── db.xlsx                        # Production database export
    ├── exam_codes.xlsx                # Exam catalogue export
    └── *.sql                          # Reference SQL scripts
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

| Homescreen (Pending Tab) | Homescreen (Pending Tab — cont.) |
|:---:|:---:|
| ![Homescreen 1](media/screenshots/homescreen1.png) | ![Homescreen 2](media/screenshots/homescreen2.png) |

| Dashboard Overview | Auto-Assignment (Assigned Tab) |
|:---:|:---:|
| ![Dashboard](media/screenshots/dashboard_blurred.png) | ![Auto-Assign](media/screenshots/auto-assign.png) |

| Filtering & Search | Multiple Selection |
|:---:|:---:|
| ![Filtering](media/screenshots/filtering.png) | ![Multiple Select](media/screenshots/multipleselect.png) |

</div>

---

### 🧮 Rule Engine & Scoring

<div align="center">

| Alternatives Modal | Scoring System Breakdown |
|:---:|:---:|
| ![Alternatives](media/screenshots/alternatives_blurred.png) | ![Scoring System](media/screenshots/scoring-system.png) |

| Score Detail | Assignment Flow Diagram |
|:---:|:---:|
| ![Scoring](media/screenshots/scoring.png) | ![Flow](media/screenshots/flow.png) |

| Auto-Assign Rule Tag |  |
|:---:|:---:|
| ![Auto-Assign Tag](media/screenshots/red-comment_auto-assign.png) |  |

</div>

---

### 🔐 Admin Control Panel

<div align="center">

| Diagnosticians Management | Availability Calendar |
|:---:|:---:|
| ![Admin Diagnosticians](media/screenshots/admin_diagnosticians.png) | ![Admin Availability](media/screenshots/admin_availability.png) |

| Capacity Matrix | Skills Matrix |
|:---:|:---:|
| ![Admin Skills 1](media/screenshots/admin_skills1_blurred.png) | ![Admin Skills 2](media/screenshots/admin_skills2.png) |

| Partnerships | Παμμακάριστος Schedule |
|:---:|:---:|
| ![Admin Partners](media/screenshots/admin_partners.png) | ![Admin Pammakaristos](media/screenshots/admin_pammakaristos.png) |

| Rules Editor | Exclusive Labs & Capacity per Modality |
|:---:|:---:|
| ![Admin Advanced 1](media/screenshots/admin_advanced1.png) | ![Admin Advanced 2](media/screenshots/admin_advanced2.png) |

| Scoring Weights Editor |  |
|:---:|:---:|
| ![Admin Advanced 3](media/screenshots/admin_advanced3.png) |  |

</div>

---

## 📄 License

Internal proprietary software — **Kosmoiatriki © 2026**. All rights reserved.

---

<div align="center">
  <img src="media/logo_multiple.png" alt="DiagFlow Logo" height="50" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="media/textbox.png" alt="DiagFlow Textbox" height="50" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="media/logo_transparent_crop.png" alt="DiagFlow Transparent Logo" height="50" />
</div>
