"""One media worker and one public gateway; only the visitor port is exposed."""
from pathlib import Path
import os
import signal
import subprocess
import sys
import time
import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def validate_environment():
    from cryptography.fernet import Fernet
    try:
        Fernet(os.environ["STUDIO_MASTER_KEY"].encode("ascii"))
    except (KeyError, ValueError, UnicodeError):
        raise RuntimeError("Set STUDIO_MASTER_KEY to a persistent 32-byte base64 encryption key.") from None
    if not os.environ.get("STUDIO_PUBLIC_HOSTS") and os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
        os.environ["STUDIO_PUBLIC_HOSTS"] = os.environ["RENDER_EXTERNAL_HOSTNAME"]
    if not os.environ.get("STUDIO_PUBLIC_HOSTS"):
        raise RuntimeError("Set STUDIO_PUBLIC_HOSTS to the public hostname (without https://).")
    from app import store, media
    from app.providers import has_credentials
    if not has_credentials(store.settings()) and os.environ.get("STUDIO_ALLOW_PREVIEW_ONLY") != "1":
        raise RuntimeError("Configure STUDIO_KLING_API_KEY in the cloud provider's secret settings.")
    if not (media.FFMPEG.is_file() and media.FFPROBE.is_file() and media.FONT.is_file()):
        raise RuntimeError("FFmpeg or Chinese fonts are unavailable.")
    voices = media.TTS_ROOT / "models/kokoro-v1.1-zh/voices"
    if not media.TTS_PYTHON.is_file() or not all((voices / (v + ".pt")).is_file() for v in ("zf_001", "zf_003", "zm_010", "zm_009")):
        raise RuntimeError("Chinese Kokoro model files are unavailable.")
    # Validate the key without logging it. Environment supplies cloud credentials.
    probe = store.protect("cloud-storage-check")
    assert store.protect(probe, decrypt=True) == "cloud-storage-check"


def main():
    validate_environment()
    children = []
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        core = subprocess.Popen([sys.executable, "-B", str(ROOT / "run.py")], cwd=ROOT)
        children.append(core)
        for _ in range(60):
            if stopped or core.poll() is not None:
                raise RuntimeError("Private worker did not start.")
            try:
                r = httpx.get("http://127.0.0.1:8787/api/bootstrap", timeout=2)
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.5)
        else:
            raise RuntimeError("Private worker startup timed out.")
        gateway = subprocess.Popen([sys.executable, "-B", "-m", "uvicorn", "app.share:app", "--host", "0.0.0.0", "--port", os.environ.get("PORT", "8080"), "--no-access-log", "--no-proxy-headers"], cwd=ROOT)
        children.append(gateway)
        while not stopped:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A studio process exited; the container must restart.")
            time.sleep(.5)
    finally:
        # Stop public requests first, then allow the media worker a graceful shutdown.
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in reversed(children):
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
