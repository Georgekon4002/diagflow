"""
DiagFlow — EXE Build Script

Uses PyInstaller to package DiagFlow into a standalone Windows EXE.

Usage:
    python scripts/build_exe.py

Prerequisites:
    pip install pyinstaller

Output:
    dist/DiagFlow.exe
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
FRONTEND = ROOT / "frontend"


def build():
    print("=" * 60)
    print("  DiagFlow EXE Builder")
    print("=" * 60)

    # Ensure PyInstaller is available
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("\n  PyInstaller not found. Installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    # Build the PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",               # No terminal window — desktop app feel
        "--name", "DiagFlow",
        "--icon", str(ROOT / "media" / "logo.ico"),  # Use .ico format for Windows EXE
        # Include the frontend directory as bundled data
        "--add-data", f"{FRONTEND};frontend",
        # Include the src package
        "--paths", str(SRC),
        # Hidden imports that PyInstaller may miss
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "anyio",
        "--hidden-import", "anyio._backends._asyncio",
        "--hidden-import", "diagflow.main",
        "--hidden-import", "diagflow.api.routes",
        "--hidden-import", "diagflow.api.schemas",
        "--hidden-import", "diagflow.api.dependencies",
        "--hidden-import", "diagflow.services.assignment",
        "--hidden-import", "diagflow.services.diagnostician",
        "--hidden-import", "diagflow.services.pamakristos",
        "--hidden-import", "diagflow.services.comment_parser",
        "--hidden-import", "diagflow.engine.pipeline",
        "--hidden-import", "diagflow.engine.filters",
        "--hidden-import", "diagflow.engine.scoring",
        "--hidden-import", "diagflow.engine.rules",
        "--hidden-import", "diagflow.engine.solver",
        "--hidden-import", "diagflow.config",
        "--hidden-import", "diagflow.utils.logging",
        "--hidden-import", "structlog",
        "--hidden-import", "pydantic_settings",
        # Entry point
        str(SRC / "diagflow" / "launcher.py"),
    ]

    print(f"\n  Running PyInstaller...")
    print(f"  Output: {ROOT / 'dist' / 'DiagFlow.exe'}\n")

    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode == 0:
        print("\n" + "=" * 60)
        print("  BUILD SUCCESSFUL!")
        print(f"  EXE location: {ROOT / 'dist' / 'DiagFlow.exe'}")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("  BUILD FAILED. Check output above for errors.")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    build()
