"""Keep a visitor-only tunnel alive and update the stable GitHub Pages entry."""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.share import share_code

WORK = ROOT / "work"
STATE = ROOT / "data/sharing-state.json"
STOP = WORK / "share-stop"
PYTHON = ROOT / ".venv/Scripts/python.exe"
SSH = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32/OpenSSH/ssh.exe"
CLOUDFLARED = Path(os.environ.get("STUDIO_CLOUDFLARED", str(ROOT / "work/tools/cloudflared.exe")))
PROJECT = json.loads((ROOT / "deploy/project.json").read_text(encoding="utf-8"))
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def save(value):
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, STATE)


def ready(url):
    try:
        response = httpx.get(url, timeout=3)
        return response.status_code == 200 and response.json()
    except (httpx.HTTPError, ValueError):
        return None


def main():
    WORK.mkdir(exist_ok=True)
    cloud_state = ROOT / "data/cloud-deployment.json"
    if cloud_state.exists() and json.loads(cloud_state.read_text(encoding="utf-8")).get("ready"):
        print("Verified cloud backend is active; local sharing is unnecessary.", flush=True)
        return
    STOP.unlink(missing_ok=True)
    (WORK / "share-supervisor.pid").write_text(str(os.getpid()), encoding="ascii")
    env = os.environ.copy()
    env.update(TEMP=str(WORK), TMP=str(WORK), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", STUDIO_NO_BROWSER="1")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "start.ps1")], cwd=ROOT, env=env, check=True, creationflags=FLAGS)
    gateway = None
    if not ready("http://127.0.0.1:8788/api/share/status"):
        with (WORK / "share-gateway.log").open("ab") as output:
            gateway = subprocess.Popen([str(PYTHON), "-B", str(ROOT / "run_share.py")], cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT, creationflags=FLAGS)
        for _ in range(40):
            if ready("http://127.0.0.1:8788/api/share/status"):
                break
            if gateway.poll() is not None:
                raise RuntimeError("Visitor gateway exited. Check work/share-gateway.log.")
            time.sleep(.5)
        else:
            raise RuntimeError("Visitor gateway did not become ready.")
    gateway_pid_file = WORK / "share-gateway.pid"
    gateway_pid = int(gateway_pid_file.read_text(encoding="ascii")) if gateway_pid_file.exists() else (gateway.pid if gateway else None)
    state = {"supervisor_pid": os.getpid(), "gateway_pid": gateway_pid, "tunnel_pid": None, "url": None, "pages_url": PROJECT["pages_url"], "online": False}
    save(state)
    tunnel = None
    published_url = None
    retry_at = 0
    cloud_attempted = False
    connection_started = 0
    try:
        while not STOP.exists():
            if tunnel is None or tunnel.poll() is not None:
                if tunnel is not None:
                    time.sleep(4)
                log_path = WORK / "sharing-tunnel.log"
                provider = "cloudflare" if CLOUDFLARED.exists() and not cloud_attempted else "ssh"
                if provider == "cloudflare":
                    cloud_attempted = True
                    command = [str(CLOUDFLARED), "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8788", "--protocol", "http2", "--edge-ip-version", "4"]
                else:
                    command = [str(SSH), "-T", "-R", "80:127.0.0.1:8788", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", "-o", "ExitOnForwardFailure=yes", "-o", "BatchMode=yes", "-o", "IdentityAgent=none", "-o", "IdentitiesOnly=yes", "-o", "IdentityFile=none", "-o", "StrictHostKeyChecking=accept-new", "-o", "UserKnownHostsFile=" + str(WORK / "tunnel-known-hosts"), "nokey@localhost.run"]
                with log_path.open("wb") as output:
                    tunnel = subprocess.Popen(command, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT, creationflags=FLAGS)
                state.update(tunnel_pid=tunnel.pid, online=False, provider=provider)
                connection_started = time.time()
                save(state)
                address = None
                for _ in range(45):
                    if STOP.exists() or tunnel.poll() is not None:
                        break
                    log = log_path.read_text(encoding="utf-8", errors="replace")
                    matches = re.findall(r"https://[a-z0-9-]+\.(?:lhr\.life|trycloudflare\.com)", log)
                    if matches:
                        address = matches[-1]
                        break
                    time.sleep(1)
                if not address:
                    tunnel.terminate()
                    state["message"] = "Waiting for the public connection service."
                    save(state)
                    time.sleep(5)
                    continue
                state.update(url=address, online=True, message="Public visitor connection ready")
                save(state)
                (ROOT / "docs/connection.json").write_text(json.dumps({"url": address, "access": share_code()}, ensure_ascii=False, indent=2), encoding="utf-8")
                print("Visitor connection ready:", address, flush=True)
            # The free relay can rotate its domain without ending the SSH process.
            log = (WORK / "sharing-tunnel.log").read_text(encoding="utf-8", errors="replace")
            current_urls = re.findall(r"https://[a-z0-9-]+\.(?:lhr\.life|trycloudflare\.com)", log)
            if current_urls and current_urls[-1] != state["url"]:
                state.update(url=current_urls[-1], online=True, message="Public visitor address refreshed")
                save(state)
                (ROOT / "docs/connection.json").write_text(json.dumps({"url": state["url"], "access": share_code()}, ensure_ascii=False, indent=2), encoding="utf-8")
                print("Visitor address refreshed:", state["url"], flush=True)
            if (ROOT / "data/github-publication.json").exists() and not (WORK / "pause-publication").exists() and state["url"] != published_url and time.time() >= retry_at:
                health = ready(state["url"] + "/api/share/ping")
                if not health or not health.get("online"):
                    if provider == "cloudflare" and time.time() - connection_started > 60:
                        tunnel.terminate()
                    retry_at = time.time() + 5
                    time.sleep(1)
                    continue
                result = subprocess.run([str(PYTHON), "-B", str(ROOT / "deploy/publish_github.py")], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=200, creationflags=FLAGS)
                if result.returncode == 0:
                    published_url = state["url"]
                    state["published_at"] = time.time()
                    state["publication_message"] = "Stable GitHub entry updated"
                    print("GitHub entry synchronized", flush=True)
                else:
                    state["publication_message"] = "Source synchronization needs attention; retrying in 60 seconds."
                    retry_at = time.time() + 60
                save(state)
            time.sleep(1)
    finally:
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
        if gateway and gateway.poll() is None:
            gateway.terminate()
        state.update(online=False, message="Public sharing stopped")
        save(state)


if __name__ == "__main__":
    main()
