"""Entry point used by 02_start_agent.bat: starts the local server and opens the dashboard."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.version import VERSION  # noqa: E402


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _running_version(url: str) -> str:
    """Version reported by an agent already listening on ``url`` ("" if unknown / older than 1.8)."""
    try:
        with urllib.request.urlopen(url + "/api/status", timeout=3) as resp:
            return str(json.loads(resp.read().decode("utf-8")).get("version") or "")
    except Exception:  # noqa: BLE001
        return ""


def _stop_running(url: str, host: str, port: int) -> bool:
    req = urllib.request.Request(url + "/api/admin/shutdown", data=b"", method="POST", headers={"X-KLA": "1"})
    try:
        urllib.request.urlopen(req, timeout=5).close()
    except Exception:  # noqa: BLE001 - it may close the connection while shutting down
        pass
    for _ in range(40):
        if not _port_open(host, port):
            return True
        time.sleep(0.5)
    return False


def main() -> None:
    import uvicorn

    from app.config import EnvSettings
    from app.main import create_app

    env = EnvSettings()
    host = env.app_host
    if host not in ("127.0.0.1", "localhost"):
        print("WARNING: APP_HOST is not local; forcing 127.0.0.1 for safety.")
        host = "127.0.0.1"
    url = f"http://{host}:{env.app_port}"
    if _port_open(host, env.app_port):
        running = _running_version(url)
        if running == VERSION:
            print(f"Khalid Leads Agent is already running: {url}")
            if env.open_browser_on_start:
                webbrowser.open(url)
            return
        # An older copy is still running (e.g. updated without 03_stop_agent.bat): replace it.
        print(f"Stopping the running Khalid Leads Agent ({running or 'old version'}) to start {VERSION} ...")
        if not _stop_running(url, host, env.app_port):
            print(f"ERROR: could not stop the running agent on {url}. Run 03_stop_agent.bat, then start again.")
            return

    pid_file = env.data_path / "agent.pid"
    env.data_path.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()), encoding="ascii")

    app = create_app()
    config = uvicorn.Config(app, host=host, port=env.app_port, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    app.state.server = server

    if env.open_browser_on_start:
        def _open() -> None:
            for _ in range(60):
                if _port_open(host, env.app_port):
                    webbrowser.open(url)
                    return
                time.sleep(0.5)
        threading.Thread(target=_open, daemon=True).start()

    print(f"Khalid Leads Agent: {url}")
    try:
        server.run()
    finally:
        try:
            pid_file.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
