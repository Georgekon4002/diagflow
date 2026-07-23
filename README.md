# DiagFlow

**Automated CT/MRI Report Assignment Engine for Kosmoiatriki**

DiagFlow replaces the manual process of assigning CT and MRI medical-imaging reports to diagnosticians via Infomed's Slis system. It uses a rule-based engine with hard filters, weighted scoring, and Google OR-Tools (CP-SAT) batch optimisation to suggest optimal assignments. A secretariat operator can confirm or override each suggestion with one click through a dedicated dashboard.

> **Design philosophy:** *Suggest, don't decide.* Every suggestion comes with a visible explanation of which rules fired and why. Even eliminated candidates are shown so the operator can override when needed. Every human override is logged for auditing and future weight tuning.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Rule Engine](#rule-engine)
- [Data Model](#data-model)
- [API Reference](#api-reference)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)
- [UML Diagrams](#uml-diagrams)
- [License](#license)

---

## Features

| Area | Description |
|------|-------------|
| **Rule-based assignment engine** | Hard filters → weighted scoring → solver pipeline with full transparency |
| **OR-Tools CP-SAT solver** | Batch optimisation when multiple exams are pending simultaneously |
| **Near-tie load balancing** | Candidates within a configurable score tolerance are ranked by workload instead of score, preventing repeated assignments to the same person |
| **Auto-assignments** | Exclusive partnerships, Παμμακάριστος on-call rotation, and special exam codes are assigned automatically without manual intervention |
| **Slis synchronisation** | Two-way sync — pull pending exams on startup, push confirmed assignments back; daily background sync of diagnostician/doctor master data via APScheduler |
| **Secretariat dashboard** | Tabbed interface (Pending / Assigned) with real-time suggest → confirm/override workflow, bulk operations, and Slis push |
| **Admin panel** | Authenticated panel for managing diagnosticians, skills, partnerships, doctors, availability, and Παμμακάριστος weekly schedule |
| **Full audit trail** | Every decision logged with rule breakdown, scores, alternatives, and override reasons |
| **Standalone EXE** | PyInstaller-based build with embedded pywebview window for desktop deployment |

---

## Architecture

```
                 ┌────────────────────┐
                 │  Slis DB (MSSQL)   │    ← production (read-only)
                 │  mock_slis.db      │    ← development (SQLite)
                 └─────────┬──────────┘
                   pull /  │  \ push
                 ──────────┼────────────
                           ▼
              ┌──────────────────────────┐
              │  DiagFlow FastAPI Server │
              │                          │
              │  ┌─────────────────────┐ │       ┌─────────────┐
              │  │  Slis Sync Service  │◄├───────┤ APScheduler │
              │  └─────────────────────┘ │       │ (daily 3 AM)│
              │                          │       └─────────────┘
              │  ┌─────────────────────┐ │
              │  │   Assignment Svc    │ │
              │  │   Diagnostician Svc │ │
              │  │   Παμμακάριστος Svc │ │
              │  └────────┬────────────┘ │
              │           │              │
              │  ┌────────▼────────────┐ │
              │  │    Rule Engine      │ │
              │  │  Filters → Scoring  │ │
              │  │     → Solver        │ │
              │  └─────────────────────┘ │
              │                          │
              │  ┌─────────────────────┐ │
              │  │   diagflow.db       │ │    ← config, skills,
              │  │   (SQLite)          │ │      partnerships,
              │  └─────────────────────┘ │      availability, logs
              └──────────┬───────────────┘
                         │ REST API (/api/*)
                         │ Static files (/)
                         ▼
              ┌──────────────────────────┐
              │  Secretariat Dashboard   │    index.html — pending/assigned tabs
              │  Admin Panel             │    admin.html — configuration management
              └──────────────────────────┘
```

### Dual-Database Pattern

DiagFlow uses **two separate SQLite databases**:

| Database | Path | Purpose |
|----------|------|---------|
| `mock_slis.db` | `db/mock_slis.db` | Mirrors the Slis exam data (read + write-back). In production, this is replaced by MSSQL via pyodbc. |
| `diagflow.db` | `db/diagflow.db` | DiagFlow's own config & state — diagnosticians, skills, partnerships, availability, local assignments, assignment log, Παμμακάριστος schedule. |

Both use raw `sqlite3` (no ORM in production code) for simplicity and consistency.

---

## Rule Engine

The engine processes each pending exam through a four-stage pipeline:

### Stage 0: Exclusive Partnerships (bypass)

If the issuing doctor has an **active exclusive partnership**, the exam is assigned directly — no filters or scoring run.

### Stage 1: Hard Filters (must pass)

Candidates failing any hard filter are **eliminated** from scoring but still shown in the UI alternatives list (with a red indicator and the elimination reason) so the operator can override.

| Filter | Description |
|--------|-------------|
| **Availability** | Is the diagnostician working today? Not on leave? |
| **Capacity** | Has the diagnostician reached their daily quota for today's weekday? |
| **Modality** | Can they handle CT / MRI / MRA? |
| **Skills** | If an explicit skill record exists for the exam code **and** proficiency is 0 → eliminated. No data = pass (gets neutral score later). |

> **Note:** Comment exclusion (LLM-based) and lab preference are preserved in code but disabled. Lab preference is now a weighted scoring factor.

### Stage 2: Weighted Scoring

Each surviving candidate receives a composite score (0.0–1.0):

| Factor | Weight | Description |
|--------|--------|-------------|
| **Partnership** | 0.35 | Issuing doctor has a preferred diagnostician? |
| **Patient History** | 0.20 | Continuity of care — same diagnostician for same patient's past exams |
| **Skills** | 0.20 | Exam code proficiency bonus (preferred = 1.0, neutral = 0.5, no data = 0.3) |
| **Lab Preference** | 0.15 | Diagnostician's preferred lab matches the exam's lab |
| **Capacity** | 0.10 | Remaining quota ratio — more availability = higher score |

Weights are fully configurable via environment variables.

### Stage 3: Near-Tie Load Balancing

Candidates within `SCORE_TIE_TOLERANCE` (default 5%) of the top score are treated as a **near-tie group**. Within this group, ranking switches from score to:
1. Fewest exams assigned today
2. Largest daily quota
3. Random jitter (final tie-break)

This prevents the same diagnostician from receiving all proposals when equally-good candidates exist.

### Stage 4: Solver

- **Single exam:** Greedy pick (highest-scored candidate after tie-breaking)
- **Batch:** OR-Tools CP-SAT maximises total score across all assignments while respecting daily quotas

### Pipeline Flow

```
Pending Exam
    │
    ├─ Exclusive Partnership? ──yes──► Direct Assignment
    │
    ▼
Hard Filters (Availability → Capacity → Modality → Skills)
    │
    ▼
Weighted Scoring (Partnership + History + Skills + Lab + Capacity)
    │
    ▼
Near-Tie Load Balancing (within tolerance → sort by workload)
    │
    ▼
Solver (Greedy or CP-SAT)
    │
    ▼
Suggestion + Score Breakdown + Alternatives + Audit Trail
    │
    ▼
Human Review (Confirm / Override)
```

---

## Data Model

### DiagFlow Config Database (`diagflow.db`)

| Table | Purpose |
|-------|---------|
| `diagnosticians` | Master list: id, name, active, can_ct, can_mri, per-weekday quotas, preferred_lab_id |
| `diagnostician_skills` | Exam code → diagnostician mapping with is_preferred flag |
| `partnerships` | Issuing doctor → preferred diagnostician with exclusive/active flags |
| `availability` | Daily calendar: on_leave, Παμμακάριστος on-call |
| `doctors` | Master list of issuing doctors (synced from Slis) |
| `local_assignments` | Locally assigned exams not yet pushed to Slis |
| `assignment_log` | Audit trail: exammoreid, diagnostician_id, assigned_at |
| `pamakristos_schedule` | Weekly on-call rotation (weekday → diagnostician_id) |

### Mock Slis Database (`mock_slis.db`)

| Table | Purpose |
|-------|---------|
| `slis_exams` | Mirrors the Slis `#TMP_LIST` result set — one row per exam instance |
| `exam_categories` | Lookup: examnumcode → category (CT/MRI/MRA) |
| `diagnosticians` | Slis personnel table (PERSONELID, DOCNAME) |
| `doctors` | Slis doctors table (CODE, DOCNAME) |

See the full ER diagram in [`puml/er_diagram.puml`](puml/er_diagram.puml).

---

## API Reference

All endpoints are prefixed with `/api`. Interactive docs are available at `/docs` (Swagger UI).

### Exam Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/exams/pending` | List pending (unassigned) exams |
| `GET` | `/api/exams/assigned` | List locally assigned exams (not yet synced to Slis) |

### Assignment Engine

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/assignments/suggest` | Generate assignment suggestion for an exam |
| `POST` | `/api/assignments/confirm` | Confirm the suggested assignment |
| `POST` | `/api/assignments/override` | Override with a different diagnostician |
| `POST` | `/api/assignments/bulk-confirm` | Confirm suggestions for multiple exams |
| `POST` | `/api/assignments/bulk-override` | Override multiple exams to one diagnostician |

### Slis Sync

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/slis/pull` | Refresh exam data from Slis (or mock DB) |
| `POST` | `/api/slis/push-all` | Push all locally assigned exams to Slis |
| `POST` | `/api/slis/push-selected` | Push specific exams by exammoreid list |

### Diagnosticians & Παμμακάριστος

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/diagnosticians` | List all active diagnosticians with current workload |
| `GET` | `/api/pamakristos/oncall` | Get today's on-call diagnostician |
| `GET` | `/api/pamakristos/schedule` | Get weekly on-call schedule |
| `POST` | `/api/pamakristos/oncall` | Set on-call for a specific date |

### Admin (requires `X-Admin-Token` header)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/admin/auth/login` | Authenticate admin user |
| `GET/POST` | `/api/admin/diagnosticians` | List / create diagnosticians |
| `PUT/DELETE` | `/api/admin/diagnosticians/{id}` | Update / delete a diagnostician |
| `GET/POST/PATCH/DELETE` | `/api/admin/partnerships` | CRUD partnerships |
| `GET/POST/DELETE` | `/api/admin/doctors` | CRUD doctors |
| `GET/POST` | `/api/admin/availability` | List / set availability |
| `GET/POST/DELETE` | `/api/admin/skills` | CRUD diagnostician skills |
| `GET/POST` | `/api/admin/oncall` | Get / set Παμμακάριστος on-call |
| `GET/POST` | `/api/admin/pamakristos/weekly-schedule` | Get / update weekly rotation |
| `POST` | `/api/admin/sync-diagnosticians` | Sync diagnosticians from Slis |
| `POST` | `/api/admin/sync-doctors` | Sync doctors from Slis |
| `GET` | `/api/admin/exam-categories` | List exam categories |
| `GET` | `/api/health` | Health check |

---

## Getting Started

### Prerequisites

- **Python 3.11+**
- **SQL Server** (MSSQL) + ODBC Driver 17 — required for production Slis access
- **SQLite** — used for development (no extra install needed)

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd diagflow

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
copy .env.example .env          # Windows
# cp .env.example .env          # Linux/macOS
```

### Configuration

Key environment variables (see [`.env.example`](.env.example)):

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_MOCK_SLIS_DB` | `true` | Use local SQLite instead of real Slis MSSQL |
| `MOCK_SLIS_DB_PATH` | `db/mock_slis.db` | Path to the SQLite mock database |
| `SLIS_DB_CONNECTION_STRING` | — | SQLAlchemy MSSQL connection string |
| `WEIGHT_PARTNERSHIP` | `0.35` | Scoring weight for doctor partnerships |
| `WEIGHT_PATIENT_HISTORY` | `0.20` | Scoring weight for patient continuity |
| `WEIGHT_SKILLS` | `0.20` | Scoring weight for exam specialisation |
| `WEIGHT_LAB` | `0.15` | Scoring weight for lab preference |
| `WEIGHT_CAPACITY` | `0.10` | Scoring weight for remaining quota |
| `SCORE_TIE_TOLERANCE` | `0.05` | Near-tie threshold for load balancing |

### Database Setup

```bash
# Initialise the mock Slis database (if starting fresh)
cd db
sqlite3 mock_slis.db < init.sql
python seed_mock_db.py
cd ..

# The diagflow.db is auto-created from init_diagflow.sql
sqlite3 db/diagflow.db < db/init_diagflow.sql
```

### Running

```bash
# Start the API server (development)
uvicorn src.diagflow.main:app --reload --port 8000

# The secretariat dashboard is served at http://localhost:8000
# The admin panel is at http://localhost:8000/admin.html
# The API docs are at http://localhost:8000/docs
```

### Building the Standalone EXE

```bash
python scripts/build_exe.py
# Output: dist/DiagFlow.exe
```

### Running Tests

```bash
pytest tests/ -v
```

---

## Project Structure

```
diagflow/
├── README.md
├── pyproject.toml                     # Build config, dependencies, tool settings
├── requirements.txt                   # Pinned production dependencies
├── .env.example                       # Environment variable template
├── DiagFlow.spec                      # PyInstaller spec for EXE build
│
├── db/                                # Database files & initialisation
│   ├── diagflow.db                    # DiagFlow config/state database (SQLite)
│   ├── mock_slis.db                   # Mock Slis exam database (SQLite)
│   ├── init.sql                       # Schema for mock_slis.db
│   ├── init_diagflow.sql              # Schema + seed data for diagflow.db
│   ├── init_mock_slis.sql             # Full seed data for mock_slis.db
│   ├── create_diagflow_db.py          # Python DB creation script
│   └── seed_mock_db.py                # Python seeding script
│
├── src/diagflow/                      # Python package root
│   ├── __init__.py                    # App name & version
│   ├── main.py                        # FastAPI entry point + lifespan events
│   ├── config.py                      # Pydantic Settings (env vars)
│   ├── launcher.py                    # Standalone EXE launcher (pywebview)
│   │
│   ├── api/                           # REST API layer
│   │   ├── routes.py                  # All endpoint definitions
│   │   ├── schemas.py                 # Pydantic request/response models
│   │   └── dependencies.py            # FastAPI dependency injection
│   │
│   ├── db/                            # Data access layer
│   │   ├── diagflow_db.py             # Raw SQLite CRUD for diagflow.db
│   │   ├── engines.py                 # Dual SQLAlchemy engine factory (prod)
│   │   ├── models.py                  # SQLAlchemy ORM models (reference)
│   │   └── slis_models.py             # Slis ORM models (reference)
│   │
│   ├── engine/                        # Rule engine
│   │   ├── pipeline.py                # Pipeline orchestrator
│   │   ├── filters.py                 # Hard filter implementations
│   │   ├── scoring.py                 # Weighted scoring logic
│   │   ├── solver.py                  # OR-Tools CP-SAT solver wrapper
│   │   └── rules.py                   # Rule registry & definitions
│   │
│   ├── services/                      # Business logic
│   │   ├── assignment.py              # Assignment lifecycle + auto-assign
│   │   ├── diagnostician.py           # Candidate loading & enrichment
│   │   ├── pamakristos.py             # Παμμακάριστος on-call scheduler
│   │   └── slis_sync.py               # Pull/push Slis sync + daily cron
│   │
│   └── utils/
│       └── logging.py                 # Structlog configuration
│
├── frontend/                          # Static web UI
│   ├── index.html                     # Secretariat review dashboard
│   ├── admin.html                     # Admin configuration panel
│   ├── css/styles.css                 # Shared stylesheet
│   ├── js/
│   │   ├── app.js                     # Dashboard logic
│   │   └── admin.js                   # Admin panel logic
│   └── media/                         # Icons & assets
│
├── puml/                              # PlantUML architecture diagrams
│   ├── architecture.puml              # System component diagram
│   ├── assignment_sequence.puml       # Assignment flow sequence diagram
│   ├── rule_engine_flow.puml          # Rule engine activity diagram
│   ├── data_model.puml                # Data model overview
│   ├── er_diagram.puml                # Full ER diagram (both databases)
│   ├── class_api.puml                 # API layer class diagram
│   └── data_api.puml                  # Data access class diagram
│
├── scripts/
│   ├── build_exe.py                   # PyInstaller build script
│   └── data_quality_audit.py          # Data quality analysis tool
│
├── tests/
│   ├── conftest.py                    # Shared fixtures
│   ├── test_filters.py                # Hard filter unit tests
│   ├── test_scoring.py                # Scoring logic unit tests
│   ├── test_pipeline.py               # Pipeline integration tests
│   └── test_autoassign.py             # Auto-assignment logic tests
│
└── docs/                              # Reference data & SQL
    ├── db.xlsx                        # Production database export
    ├── exam_codes.xlsx                # Exam code catalogue
    ├── init_data.xlsx                 # Initial seed data
    └── *.sql                          # Reference SQL scripts
```

---

## UML Diagrams

PlantUML diagrams are in the [`puml/`](puml/) directory. Render them with any PlantUML-compatible tool or the [PlantUML online server](https://www.plantuml.com/plantuml/uml/).

| Diagram | File | Description |
|---------|------|-------------|
| System Architecture | [`architecture.puml`](puml/architecture.puml) | High-level component diagram |
| Assignment Sequence | [`assignment_sequence.puml`](puml/assignment_sequence.puml) | End-to-end suggest → confirm/override flow |
| Rule Engine Flow | [`rule_engine_flow.puml`](puml/rule_engine_flow.puml) | Pipeline activity diagram |
| Data Model | [`data_model.puml`](puml/data_model.puml) | Data model overview |
| ER Diagram | [`er_diagram.puml`](puml/er_diagram.puml) | Full entity-relationship diagram (both databases) |
| Class — API Layer | [`class_api.puml`](puml/class_api.puml) | API routes, schemas, and service classes |
| Class — Data Access | [`data_api.puml`](puml/data_api.puml) | Data access layer class diagram |

---

## License

Internal project — Kosmoiatriki © 2026
