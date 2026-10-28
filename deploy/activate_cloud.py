"""Verify a real cloud preview before moving the existing GitHub entry."""
from pathlib import Path
import getpass
import json
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit
import httpx

ROOT = Path(__file__).resolve().parent.parent


def verify(url, code):
    with httpx.Client(timeout=40, follow_redirects=False) as client:
        ping = client.get(url + "/api/share/ping")
        ping.raise_for_status()
        if not ping.json().get("online"):
            raise RuntimeError("云端生成后台尚未就绪。")
        response = client.post(url + "/api/share/login", json={"code": code}, headers={"Origin": url})
        response.raise_for_status()
        boot = client.get(url + "/api/bootstrap")
        boot.raise_for_status()
        caps = boot.json()["capabilities"]
        if not all(caps.get(key) for key in ("ffmpeg", "tts", "kling")):
            raise RuntimeError("云端的视频、配音或可灵配置尚未就绪。")
        if client.get(url + "/api/settings").status_code != 403:
            raise RuntimeError("云端管理员配置没有正确隔离，未切换入口。")
        headers = {"Origin": url, "X-Studio-Token": boot.json()["token"]}
        response = client.post(url + "/api/plan", headers=headers, json={"brief": "一叶小舟驶入晨光中的山谷。", "style": "ink", "ratio": "9:16", "use_llm": False})
        response.raise_for_status()
        plan = response.json()
        for shot, line in zip(plan["shots"], ["一叶小舟。", "驶入山谷。", "迎接晨光。"]):
            shot["narration"] = line
        response = client.post(url + "/api/jobs", headers=headers, json={"mode": "preview", "plan": plan, "voice": caps["voices"][0], "idempotency": uuid.uuid4().hex, "paid_consent": False})
        response.raise_for_status()
        job_id = response.json()["id"]
        print("正在验证云端中文配音与视频合成；本次不提交付费视频生成。", flush=True)
        for _ in range(150):
            response = client.get(url + "/api/jobs/" + job_id)
            response.raise_for_status()
            job = response.json()
            if job["status"] == "completed":
                break
            if job["status"] in {"failed", "unknown", "paused"}:
                raise RuntimeError("云端预演未完成，原入口保持不变。")
            time.sleep(3)
        else:
            raise RuntimeError("云端预演超时，原入口保持不变；请到云平台查看原任务。")
        video = client.get(url + "/api/jobs/" + job_id + "/file/video", headers={"Range": "bytes=0-1023"})
        if video.status_code != 206:
            raise RuntimeError("成片读取未通过，原入口保持不变。")
        return {"cloud_preview_job": job_id, "video_range": 206, "paid_generation_submitted": False}


def main():
    url = input("云端 HTTPS 网址：").strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 443} or parsed.path or parsed.query or parsed.fragment:
        raise RuntimeError("请填写云平台提供的网址，格式为 https://你的服务域名")
    code = getpass.getpass("云平台 STUDIO_SHARE_CODE 体验码：").strip()
    if not code:
        raise RuntimeError("体验码不能为空。")
    report = verify(url, code)
    pointer = ROOT / "docs/connection.json"
    previous = pointer.read_bytes()
    pause = ROOT / "work/pause-publication"
    own_pause = not pause.exists()
    pause.write_text("Activating verified cloud backend", encoding="ascii")
    try:
        pointer.write_text(json.dumps({"mode": "cloud", "hostname": parsed.hostname, "url": url, "access": code}, ensure_ascii=False, indent=2), encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", str(ROOT / "deploy/publish_github.py")], cwd=ROOT, capture_output=True)
        if result.returncode:
            pointer.write_bytes(previous)
            raise RuntimeError("GitHub 同步未完成，原入口配置已恢复。请检查网络后重试。")
        report.update(url=url, ready=True, activated_at=time.time())
        (ROOT / "data/cloud-deployment.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (ROOT / "work/share-stop").write_text("cloud backend activated", encoding="ascii")
        print("云端预演通过，固定分享入口已切换。现在可关闭本机，用手机流量复核。")
    finally:
        if own_pause:
            pause.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
