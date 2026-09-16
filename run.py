"""Runs the whole local demo stack with one command: brings up Postgres and
LiveKit via Docker, then starts the agent worker, the token server, and the
web page's static server as subprocesses, streaming all their output here.

    .venv\\Scripts\\python run.py

Ctrl+C stops the worker/token-server/web-server. Docker containers are left
running (stop those separately with `docker compose down` if you want them
down too -- they're meant to persist across restarts, unlike these three).
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

print = functools.partial(print, flush=True)  # stdout is often piped, not a TTY -- force flushing

ROOT = Path(__file__).parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

# Read from the environment (.env, loaded below into `env` and passed to each
# subprocess) rather than hardcoding -- so running against a non-default
# .env (e.g. a second, side-by-side stack on different ports) actually takes
# effect here too, instead of always landing on 8080/5500 regardless.
TOKEN_SERVER_PORT = os.environ.get("TOKEN_SERVER_PORT", "8080")
WEB_PORT = os.environ.get("WEB_PORT", "5500")

SERVICES = [
    {
        "name": "worker",
        "cmd": [PYTHON, "-m", "receptionist.worker", "dev"],
        "cwd": ROOT,
    },
    {
        "name": "token",
        "cmd": [
            PYTHON, "-m", "uvicorn", "server.token_server:app",
            "--host", "127.0.0.1", "--port", TOKEN_SERVER_PORT,
        ],
        "cwd": ROOT,
    },
    {
        "name": "web",
        "cmd": [PYTHON, "web/serve.py"],
        "cwd": ROOT,
        # No docker port-remapping in this local (non-container) path, so
        # the browser-facing token URL is just this same host port directly.
        "extra_env": {"WEB_PORT": WEB_PORT, "TOKEN_SERVER_URL": f"http://localhost:{TOKEN_SERVER_PORT}"},
    },
]


def _ensure_docker_services() -> bool:
    if shutil.which("docker") is None:
        print("[run] docker not found on PATH -- make sure Postgres and LiveKit are running yourself.")
        return False

    print("[run] starting docker services (postgres, livekit)...")
    result = subprocess.run(["docker", "compose", "up", "-d"], cwd=ROOT)
    if result.returncode != 0:
        print("[run] docker compose up failed -- is Docker Desktop running? Continuing anyway.")
        return False

    print("[run] waiting for postgres to be healthy...")
    for _ in range(30):
        check = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", "gpt-live-postgres-1"],
            capture_output=True,
            text=True,
        )
        if check.stdout.strip() == "healthy":
            print("[run] postgres is healthy.")
            return True
        time.sleep(1)
    print("[run] postgres didn't report healthy in time -- continuing anyway.")
    return False


def _stream_output(name: str, proc: subprocess.Popen) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        print(f"[{name}] {line}", end="")


def main() -> None:
    _ensure_docker_services()

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONUNBUFFERED"] = "1"  # so worker/token-server output streams live too, not just at exit

    procs: list[subprocess.Popen] = []
    reported_exit: set[str] = set()

    for service in SERVICES:
        service_env = {**env, **service.get("extra_env", {})}
        proc = subprocess.Popen(
            service["cmd"],
            cwd=str(service["cwd"]),
            env=service_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        procs.append(proc)
        threading.Thread(target=_stream_output, args=(service["name"], proc), daemon=True).start()
        print(f"[run] started {service['name']} (pid {proc.pid})")

    print(f"[run] all services started. Open http://localhost:{WEB_PORT}")
    print("[run] press Ctrl+C to stop the worker/token-server/web-server.")

    try:
        while True:
            for proc, service in zip(procs, SERVICES):
                code = proc.poll()
                if code is not None and service["name"] not in reported_exit:
                    reported_exit.add(service["name"])
                    print(f"[run] {service['name']} exited with code {code}")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n[run] stopping services...")
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("[run] stopped. (docker services are still running -- `docker compose down` to stop those too)")


if __name__ == "__main__":
    main()
