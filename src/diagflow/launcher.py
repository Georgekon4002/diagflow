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

import logging
from logging.handlers import RotatingFileHandler
import os
import socket
import sys
import time
import traceback
import threading
import webbrowser
from pathlib import Path

# Force UTF-8 encoding for standard output to prevent UnicodeEncodeError on Windows
os.environ["PYTHONIOENCODING"] = "utf-8"

from diagflow.config import settings

# ── Host & Port configuration ──
APP_HOST = (getattr(settings, "app_host", "127.0.0.1") or "127.0.0.1").strip()
APP_PORT = getattr(settings, "app_port", 8080) or 8080
_CLIENT_HOST = "127.0.0.1" if APP_HOST in ("0.0.0.0", "::", "") else APP_HOST
APP_URL = f"http://{_CLIENT_HOST}:{APP_PORT}"

# Global exception store for server thread
_SERVER_EXCEPTION = None
_UVICORN_SERVER = None
_LOG_HANDLER: RotatingFileHandler | None = None


def get_log_file_path() -> Path:
    """Get writable path to the rotating launcher log file."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        log_dir = Path(local_app_data) / "DiagFlow" / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            return log_dir / "diagflow_launcher.log"
        except OSError:
            pass
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent.parent
    return base / "diagflow_launcher.log"


class _StreamToLogger:
    """File-like stream shim for frozen --noconsole runs where sys.stdout/stderr are None."""

    encoding = "utf-8"

    def __init__(self, logger: logging.Logger, level: int) -> None:
        self._logger = logger
        self._level = level
        self._guard = threading.local()

    def write(self, message: str) -> int:
        if not message:
            return 0
        # Re-entrancy guard prevents infinite recursion if any logging handler writes to stdout/stderr
        if getattr(self._guard, "active", False):
            return len(message)
        self._guard.active = True
        try:
            text = message.rstrip("\r\n")
            if text:
                self._logger.log(self._level, text)
        finally:
            self._guard.active = False
        return len(message)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


def _configure_launcher_logging() -> logging.Logger:
    """Configure rotating file logging and guard sys.stdout/sys.stderr for --noconsole EXEs."""
    global _LOG_HANDLER
    launcher_logger = logging.getLogger("diagflow.launcher")
    launcher_logger.setLevel(logging.INFO)
    # CRITICAL: Never propagate to root logger — setup_logging() attaches a StreamHandler(sys.stdout)
    # to root, which would otherwise loop back into _StreamToLogger and hit RecursionError.
    launcher_logger.propagate = False
    if not launcher_logger.handlers:
        try:
            log_path = get_log_file_path()
            _LOG_HANDLER = RotatingFileHandler(
                log_path,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            _LOG_HANDLER.setFormatter(
                logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
            )
            launcher_logger.addHandler(_LOG_HANDLER)
        except Exception:
            pass

    if sys.stdout is None:
        sys.stdout = _StreamToLogger(launcher_logger, logging.INFO)  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _StreamToLogger(launcher_logger, logging.ERROR)  # type: ignore[assignment]
    return launcher_logger


_LAUNCHER_LOGGER = _configure_launcher_logging()


def log(msg: str) -> None:
    """Write log entry to stdout (if attached) and rotating launcher log file."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    try:
        if sys.stdout is not None and not isinstance(sys.stdout, _StreamToLogger):
            print(formatted, flush=True)
    except Exception:
        pass
    try:
        _LAUNCHER_LOGGER.info(msg)
    except Exception:
        pass


def show_error_dialog(title: str, message: str) -> None:
    """Show native Windows error popup dialog so user/admin sees exact issue when console=False."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
    except Exception:
        pass


def show_info_dialog(title: str, message: str) -> None:
    """Show native Windows info dialog."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)  # MB_ICONINFORMATION
    except Exception:
        pass


def _is_port_in_use(host: str, port: int) -> bool:
    """Check if the target host/port is already bound."""
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((probe_host, port)) == 0


def _is_existing_diagflow_healthy() -> bool:
    """Return True if an already-running DiagFlow server responds healthy on APP_URL."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{APP_URL}/api/health", timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_frontend_dir() -> str:
    """Resolve the path to the frontend directory."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent.parent

    return str(base / "frontend")


def start_server() -> None:
    """Start the uvicorn server in a background thread."""
    global _SERVER_EXCEPTION, _UVICORN_SERVER
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

        config = uvicorn.Config(
            app,
            host=APP_HOST,
            port=APP_PORT,
            log_level="warning",
            log_config=None,  # Safe under PyInstaller --noconsole (avoids DefaultFormatter.isatty crash)
            access_log=False,
        )
        _UVICORN_SERVER = uvicorn.Server(config)
        _UVICORN_SERVER.run()
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            return
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


def main() -> None:
    """Main entry point: start server, wait for it, open window or fallback browser."""
    log("=" * 50)
    log("  DiagFlow — Starting application...")
    log(f"  Bind: {APP_HOST}:{APP_PORT}  |  URL: {APP_URL}")
    log("=" * 50)

    # Pre-check if port is already bound before spawning Uvicorn
    if _is_port_in_use(APP_HOST, APP_PORT):
        if _is_existing_diagflow_healthy():
            log(f"DiagFlow is already running on {APP_URL}. Opening existing instance in browser.")
            webbrowser.open(APP_URL)
            return
        err_msg = (
            f"Η θύρα {APP_PORT} χρησιμοποιείται ήδη από άλλη εφαρμογή.\n\n"
            f"Κλείστε την εφαρμογή που χρησιμοποιεί τη θύρα {APP_PORT} ή ορίστε διαφορετικό APP_PORT στο .env."
        )
        log(f"PORT CONFLICT: {err_msg}")
        show_error_dialog("DiagFlow — Port In Use", err_msg)
        sys.exit(1)

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
        err_msg += f"\n\nLog file: {get_log_file_path()}"

        log(f"LAUNCH ERROR: {err_msg}")
        show_error_dialog("DiagFlow Startup Error", err_msg)
        sys.exit(1)

    log("Backend server started successfully.")

    # Try launching webview window (lazy import so missing WebView2 still reaches fallback)
    try:
        import webview  # noqa: WPS433

        log("Opening DiagFlow app window in full screen (maximized)...")
        webview.create_window('DiagFlow - Diagnostic Routing System', APP_URL, width=1280, height=800, maximized=True)
        webview.start()
        log("DiagFlow app window closed. Shutting down server...")
    except Exception as wv_exc:
        log(f"PyWebView window failed to initialize ({wv_exc}). Falling back to default web browser.")
        try:
            webbrowser.open(APP_URL)
            log("Opened DiagFlow in default web browser.")
            show_info_dialog(
                "DiagFlow — Running in Browser",
                f"Το DiagFlow άνοιξε στον προεπιλεγμένο περιηγητή σας:\n{APP_URL}\n\n"
                "Κρατήστε αυτό το παράθυρο ανοιχτό όσο εργάζεστε.\n"
                "Πατήστε OK όταν θέλετε να τερματίσετε τον server του DiagFlow.",
            )
        except Exception as browser_exc:
            err_details = f"Failed to open window or browser: {wv_exc} / {browser_exc}"
            log(err_details)
            show_error_dialog("DiagFlow Launch Error", err_details)
            sys.exit(1)
    finally:
        if _UVICORN_SERVER:
            try:
                _UVICORN_SERVER.should_exit = True
            except Exception:
                pass
        server_thread.join(timeout=5)
        log("DiagFlow exiting cleanly.")


if __name__ == "__main__":
    main()
