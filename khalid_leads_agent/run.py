"""Entry point used by 02_start_agent.bat: starts the local server and opens the dashboard."""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


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
        print(f"Khalid Leads Agent is already running: {url}")
        if env.open_browser_on_start:
            webbrowser.open(url)
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
