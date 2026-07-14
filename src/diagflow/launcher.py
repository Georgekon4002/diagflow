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

import sys
import time
import threading
import webbrowser
from pathlib import Path


# ── Port configuration ──
APP_PORT = 8080
APP_URL = f"http://localhost:{APP_PORT}"


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
    import uvicorn

    # Patch the main.py to use the correct frontend path
    frontend_dir = get_frontend_dir()

    # Import and configure the FastAPI app
    from diagflow.main import app
    from fastapi.staticfiles import StaticFiles

    # Re-mount the frontend with the resolved path
    try:
        from fastapi.routing import Mount
        # Remove existing static mount if present
        app.routes = [r for r in app.routes if not (isinstance(r, Mount) and r.name == "frontend")]
    except Exception:
        pass

    if Path(frontend_dir).exists():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=APP_PORT,
        log_level="warning",  # Quiet in production
        access_log=False,
    )


def wait_for_server(timeout: int = 10) -> bool:
    """Poll until the server is accepting connections or timeout expires."""
    import urllib.request
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(f"{APP_URL}/api/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def main():
    """Main entry point: start server, wait for it, open browser."""
    print("=" * 50)
    print("  DiagFlow — Starting application...")
    print(f"  URL: {APP_URL}")
    print("=" * 50)

    # Start server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait for server to come up
    print("  Waiting for server to start...", end="", flush=True)
    ready = wait_for_server(timeout=15)

    if ready:
        print(" OK")
        print(f"  Opening browser at {APP_URL}")
        webbrowser.open(APP_URL)
    else:
        print(" TIMEOUT")
        print(f"  Could not verify server start. Opening browser anyway: {APP_URL}")
        webbrowser.open(APP_URL)

    print("\n  DiagFlow is running. Close this window to stop the application.")
    print("  Press Ctrl+C to exit.\n")

    # Keep the main thread alive
    try:
        server_thread.join()
    except KeyboardInterrupt:
        print("\n  Shutting down DiagFlow...")
        sys.exit(0)


if __name__ == "__main__":
    main()
