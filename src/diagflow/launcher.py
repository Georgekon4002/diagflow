"""
DiagFlow — Application Launcher

This module is the entry point for the packaged EXE.
It starts the FastAPI/uvicorn server in a background thread
and opens the application in the user's default browser.

Usage (when packaged as EXE):
    DiagFlow.exe

Usage (for testing):
    python -m diagflow.launcher
"""

import os
import sys
import time
import traceback
import threading
import webbrowser
import webview
from pathlib import Path

# Force UTF-8 encoding for standard output to prevent UnicodeEncodeError on Windows
os.environ["PYTHONIOENCODING"] = "utf-8"

# ── Port configuration ──
APP_PORT = 8080
APP_URL = f"http://127.0.0.1:{APP_PORT}"

# Global exception store for server thread
_SERVER_EXCEPTION = None


def get_log_file_path() -> Path:
    """Get path to the launcher log file."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent.parent
    return base / "diagflow_launcher.log"


def log(msg: str):
    """Write log entry to stdout and launcher log file."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted, flush=True)
    try:
        log_path = get_log_file_path()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass


def show_error_dialog(title: str, message: str):
    """Show native Windows error popup dialog so user/admin sees exact issue when console=False."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
    except Exception:
        pass


def get_frontend_dir() -> str:
    """
    Resolve the path to the frontend directory.
    Works both in development (source tree) and when packaged by PyInstaller.
    """
    if getattr(sys, "frozen", False):
        # Running inside PyInstaller bundle
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        # Running from source
        base = Path(__file__).resolve().parent.parent.parent

    return str(base / "frontend")


def start_server():
    """Start the uvicorn server in a background thread."""
    global _SERVER_EXCEPTION
    try:
        import uvicorn

        # Patch main.py to use correct frontend path
        frontend_dir = get_frontend_dir()

        from diagflow.main import app
        from fastapi.staticfiles import StaticFiles

        # Re-mount frontend with resolved path
        try:
            from fastapi.routing import Mount
            app.router.routes = [r for r in app.router.routes if not (isinstance(r, Mount) and r.name == "frontend")]
        except Exception:
            pass

        if Path(frontend_dir).exists():
            app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

        uvicorn.run(
            app,
            host="127.0.0.1",
            port=APP_PORT,
            log_level="warning",
            access_log=False,
        )
    except Exception as exc:
        _SERVER_EXCEPTION = exc
        log(f"Server thread error: {exc}\n{traceback.format_exc()}")


def wait_for_server(timeout: int = 30) -> bool:
    """Poll until the server is accepting connections or timeout expires."""
    import urllib.request
    start = time.time()
    while time.time() - start < timeout:
        if _SERVER_EXCEPTION:
            return False
        try:
            with urllib.request.urlopen(f"{APP_URL}/api/health", timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def main():
    """Main entry point: start server, wait for it, open window or fallback browser."""
    log("=" * 50)
    log("  DiagFlow — Starting application...")
    log(f"  URL: {APP_URL}")
    log("=" * 50)

    # Start server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait for server to come up
    log("Waiting for backend server to start...")
    ready = wait_for_server(timeout=30)

    if not ready:
        err_msg = "Could not verify backend server start."
        if _SERVER_EXCEPTION:
            err_msg += f"\n\nBackend Error: {_SERVER_EXCEPTION}"
        else:
            err_msg += "\n\nServer startup timed out after 30 seconds."
        
        log(f"LAUNCH ERROR: {err_msg}")
        show_error_dialog("DiagFlow Startup Error", err_msg)
        sys.exit(1)

    log("Backend server started successfully.")

    # Try launching webview window, fall back to default browser if webview fails
    try:
        log("Opening DiagFlow app window...")
        webview.create_window('DiagFlow - Diagnostic Routing System', APP_URL, width=1280, height=800)
        webview.start()
        log("DiagFlow app window closed. Exiting.")
    except Exception as wv_exc:
        log(f"PyWebView window failed to initialize ({wv_exc}). Falling back to default web browser.")
        try:
            webbrowser.open(APP_URL)
            log("Opened DiagFlow in default web browser. Press Ctrl+C in terminal or close process to exit.")
            while True:
                time.sleep(1)
        except Exception as browser_exc:
            err_details = f"Failed to open window or browser: {wv_exc} / {browser_exc}"
            log(err_details)
            show_error_dialog("DiagFlow Launch Error", err_details)
            sys.exit(1)

    sys.exit(0)

if __name__ == "__main__":
    main()

