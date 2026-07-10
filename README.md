# DiagFlow

**Automated CT/MRI Report Assignment Engine for Kosmoiatriki**

DiagFlow replaces the manual process of assigning CT and MRI medical reports to diagnosticians via Infomed's Slis system. It uses a rule-based engine powered by Google OR-Tools (CP-SAT) to suggest optimal assignments, which a secretariat operator can confirm or override with one click.

> **Design philosophy:** *Suggest, don't decide.* Every suggestion comes with a visible explanation of which rules fired and why. Every human override is logged for auditing and weight tuning.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Rule Engine](#rule-engine)
- [Data Model](#data-model)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)
- [Development Roadmap](#development-roadmap)
- [License](#license)

---

## Features

- **Rule-based assignment engine** with hard filters, weighted scoring, and soft load-balancing penalties
- **OR-Tools CP-SAT solver** for batch optimization of diagnostician assignments
- **LLM-powered comment parser** for free-text secretariat remarks (e.g., "ΟΧΙ ΝΑΤΣΙΚΑ")
- **Παμακάριστος on-call scheduler** for urgent hospital requests
- **Sub-category load balancing** — prevents overloading a diagnostician with too many of the same body-part category even within their daily quota
- **Full audit trail** — every decision logged with rule breakdown, scores, and human overrides
- **Secretariat review dashboard** — sleek UI for confirm/override workflow with real-time updates

---

## Architecture

```
Slis SQL DB (existing) ──read──► DiagFlow Service (Python/FastAPI)
                                       │
                                       ├─ Rule Engine (OR-Tools CP-SAT)
                                       ├─ Config Tables (same DB or separate)
                                       ├─ LLM Comment Parser
                                       ├─ Παμακάριστος On-Call Scheduler
                                       └─ Assignment Log (audit trail)
                                       │
                                write suggestion
                                       ▼
                          Secretariat Review Dashboard
                                       │
                              confirm / override
                                       ▼
                          Slis DB (final assignment written back)
```

The system uses a **dual-engine database pattern**: two SQLAlchemy engines (`slis_engine` for reading Slis data, `config_engine` for DiagFlow's own tables) that can point to the same physical database or be split later — a config change, not a code change.

See full diagrams in [`docs/`](docs/).

---

## Rule Engine

The engine processes each pending exam through a three-stage pipeline:

### Stage 1: Hard Filters (must satisfy)

Candidates failing any hard filter are **removed entirely** from the pool.

| Priority | Filter | Description |
|----------|--------|-------------|
| 1 | **Comments/Remarks** | LLM parses free-text for exclusions ("ΟΧΙ ΝΑΤΣΙΚΑ") or direct assignments |
| 2 | **Availability** | Is the diagnostician working today? Not on leave? |
| 5 | **Lab Preference** | Does the diagnostician accept work from this specific lab? |

### Stage 2: Weighted Scoring (should satisfy, can trade off)

Each surviving candidate receives a composite score:

| Priority | Factor | Description |
|----------|--------|-------------|
| 3 | **Capacity** | Remaining daily quota — higher remaining = higher score |
| 4 | **Skills** | Body-part / modality match strength |
| 6 | **Partnership** | Issuing doctor's preferred diagnostician |
| 7 | **Patient History** | Same diagnostician for same patient's past similar exams |

### Stage 3: Soft Load-Balancing Penalties

A penalty that grows as a diagnostician's same-day count of a specific subcategory (e.g., abdominal MRI) increases, even before hitting their hard quota. This prevents overloading with repetitive work.

### Pipeline

```
Pending Exams → Hard Filters → Candidate List → Weighted Scoring → CP-SAT Solver → Suggestion + Reasons → Human Review
```

---

## Data Model

DiagFlow adds these tables (alongside or within the Slis schema):

| Table | Purpose |
|-------|---------|
| `diagnosticians` | Master list: id, name, active status |
| `diagnostician_skills` | Body-part / modality (CT/MRI) capabilities per diagnostician |
| `diagnostician_capacity` | Daily hard quota + optional soft sub-caps per body-part |
| `diagnostician_lab_preference` | Which labs a diagnostician accepts |
| `diagnostician_availability` | Daily calendar: leave, on-call for Παμακάριστος |
| `partnerships` | Issuing doctor → preferred diagnostician mapping |
| `assignment_log` | Every decision: rules fired, scores, human overrides |

---

## Getting Started

### Prerequisites

- Python 3.11+
- SQL Server (MSSQL) — Slis database access
- ODBC Driver 17 for SQL Server

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd diagflow

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
copy .env.example .env
# Edit .env with your database connection strings and API keys
```

### Running

```bash
# Start the API server (development)
uvicorn src.diagflow.main:app --reload --port 8000

# The secretariat dashboard is served at http://localhost:8000
# The API docs are at http://localhost:8000/docs
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
├── pyproject.toml
├── requirements.txt
├── .env.example
│
├── docs/                          # PlantUML architecture diagrams
│   ├── architecture.puml
│   ├── rule_engine_flow.puml
│   ├── data_model.puml
│   └── assignment_sequence.puml
│
├── src/diagflow/
│   ├── main.py                    # FastAPI entry point
│   ├── config.py                  # Pydantic settings
│   │
│   ├── db/                        # Database layer
│   │   ├── engines.py             # Dual-engine factory
│   │   ├── models.py              # DiagFlow ORM models
│   │   └── slis_models.py         # Slis read-only reflections
│   │
│   ├── engine/                    # Rule engine
│   │   ├── pipeline.py            # Assignment pipeline orchestrator
│   │   ├── filters.py             # Hard filter implementations
│   │   ├── scoring.py             # Weighted scoring
│   │   ├── solver.py              # OR-Tools CP-SAT wrapper
│   │   └── rules.py               # Rule registry
│   │
│   ├── services/                  # Business logic
│   │   ├── assignment.py          # Assignment CRUD
│   │   ├── diagnostician.py       # Diagnostician queries
│   │   ├── comment_parser.py      # LLM comment analysis
│   │   └── pamakristos.py         # Παμακάριστος scheduler
│   │
│   ├── api/                       # REST API
│   │   ├── routes.py              # Endpoint definitions
│   │   ├── schemas.py             # Pydantic schemas
│   │   └── dependencies.py        # DI setup
│   │
│   └── utils/
│       └── logging.py             # Structured logging
│
├── scripts/
│   └── data_quality_audit.py      # Data quality analysis
│
├── frontend/                      # Secretariat review dashboard
│   ├── index.html
│   ├── css/styles.css
│   └── js/app.js
│
└── tests/
    ├── conftest.py
    ├── test_filters.py
    ├── test_scoring.py
    └── test_pipeline.py
```

---

## Development Roadmap

### Phase 0 — Current: Scaffold & Planning ✅
- [x] Architecture design
- [x] Project scaffold
- [x] Mock data models
- [x] PlantUML diagrams

### Phase 1 — Data Quality Audit
- [ ] Get Slis DB read access
- [ ] Run `scripts/data_quality_audit.py` against real data
- [ ] Analyze free-text comment patterns
- [ ] Validate skill/capacity data coverage
- [ ] Produce data quality report

### Phase 2 — Rule Engine MVP
- [ ] Implement hard filters with real Slis schema
- [ ] Implement weighted scoring
- [ ] Integrate OR-Tools solver
- [ ] Unit tests with real-world scenarios

### Phase 3 — LLM Comment Parser
- [ ] Fine-tune prompt for Greek free-text analysis
- [ ] Handle exclusion / inclusion / direct-assignment patterns
- [ ] Fallback to keyword matching

### Phase 4 — Dashboard & Integration
- [ ] Connect dashboard to live API
- [ ] Confirm/override workflow
- [ ] Write-back to Slis DB

### Phase 5 — Production Hardening
- [ ] Logging & monitoring
- [ ] Weight tuning from override history
- [ ] Παμακάριστος on-call rotation automation

---

## License

Internal project — Kosmoiatriki © 2026
