# DiagFlow — Cross-Computer Deployment & Distribution Guide

This guide provides step-by-step instructions for deploying DiagFlow to other computers, configuring database access (real MSSQL or mock SQLite), building standalone executables, and packaging GitHub releases.

---

## 1. System Requirements & Prerequisites

### Target Computer (End-User PC) Requirements
- **Operating System**: Windows 10 (64-bit) or Windows 11.
- **Microsoft Edge WebView2 Runtime**: Required for embedded desktop GUI window (Pre-installed on Windows 11 & updated Windows 10; downloadable from [Microsoft Edge WebView2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)).
- **Microsoft ODBC Driver 17 for SQL Server**: Required if connecting to real Slis MSSQL database (`USE_MOCK_SLIS_DB=false`). Downloadable from [Microsoft SQL Server ODBC Driver Downloads](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server).

---

## 2. Configuration (`.env`)

Every deployment requires a `.env` file located in the application root (or alongside `DiagFlow.exe`).

### Example `.env` File:

```ini
# ============================================================
# DiagFlow — Environment Configuration
# ============================================================

# --- Database Connection ---
# Slis DB (read-only access to existing Slis tables)
SLIS_DB_CONNECTION_STRING=mssql+pyodbc://diagflow_user:SecurePassword123!@192.168.1.100/SlisDB?driver=ODBC+Driver+17+for+SQL+Server

# Config DB (DiagFlow's own tables — can be same DB or separate)
CONFIG_DB_CONNECTION_STRING=mssql+pyodbc://diagflow_user:SecurePassword123!@192.168.1.100/SlisDB?driver=ODBC+Driver+17+for+SQL+Server

# Set to false in production to connect to real Slis SQL Server instance
USE_MOCK_SLIS_DB=false
MOCK_SLIS_DB_PATH=db/mock_slis.db

# --- Rule Engine Weights ---
WEIGHT_PARTNERSHIP=0.35
WEIGHT_PATIENT_HISTORY=0.20
WEIGHT_SKILLS=0.20
WEIGHT_LAB=0.15
WEIGHT_CAPACITY=0.10

# --- Server Settings ---
APP_HOST=127.0.0.1
APP_PORT=8080
APP_ENV=production
LOG_LEVEL=INFO
```

---

## 3. Database Connection Modes

### Mode A: Production Mode (Real Slis MSSQL Database)
1. Set `USE_MOCK_SLIS_DB=false` in `.env`.
2. Configure `SLIS_DB_CONNECTION_STRING` with valid host, port, credentials, and database name.
3. Ensure ODBC Driver 17 is installed on the target machine.
4. Verify database firewall/network access between target computer and SQL Server.

### Mode B: Standalone / Demo Mode (SQLite Mock DB)
1. Set `USE_MOCK_SLIS_DB=true` in `.env`.
2. Ensure `db/mock_slis.db` and `db/diagflow.db` are present in the `db/` folder next to the executable.

---

## 4. Building the Portable Executable (`DiagFlow.exe`)

To build an executable on a developer machine:

1. Open PowerShell / Command Prompt in the repository root.
2. Activate your virtual environment (if applicable):
   ```cmd
   .venv\Scripts\activate
   ```
3. Run the build script:
   ```cmd
   python scripts/build_exe.py
   ```
4. Output will be generated at `dist/DiagFlow.exe`.

---

## 5. Packaging a GitHub Release

When distributing DiagFlow via GitHub Releases or direct zip distribution, bundle the following files into a single `.zip` file (e.g. `DiagFlow-v1.0.0-Windows.zip`):

```text
DiagFlow-Release/
├── DiagFlow.exe              # Standalone executable
├── .env.example              # Template environment file
├── DEPLOYMENT_GUIDE.md       # Deployment instructions
├── USER_GUIDE.md             # End-user manual
└── db/                       # Initial database directory
    ├── diagflow.db           # Config & admin user database
    └── mock_slis.db          # Mock exam database (if offline mode)
```

### GitHub Release Steps:
1. Push release tag to GitHub:
   ```cmd
   git tag -a v1.0.0 -m "Release v1.0.0"
   git push origin v1.0.0
   ```
2. Navigate to **Releases** -> **Draft a new release** on GitHub.
3. Attach `DiagFlow-v1.0.0-Windows.zip`.
4. Publish the release.
