"""Real Linux CPU narration + FFmpeg preview. Never requests paid AI generation."""
import os
import time
import uuid
import httpx

base = os.environ.get("STUDIO_SMOKE_URL", "http://127.0.0.1:8080")
with httpx.Client(timeout=30) as client:
    for _ in range(90):
        try:
            r = client.get(base + "/api/share/ping")
            if r.status_code == 200 and r.json()["online"]:
                break
        except httpx.HTTPError:
            pass
        time.sleep(2)
    else:
        raise RuntimeError("Cloud worker did not become ready")
    r=client.post(base+"/api/share/login", json={"code":"cloud-smoke-test"}, headers={"Origin":base});r.raise_for_status()
    boot=client.get(base+"/api/bootstrap").json()
    assert boot["capabilities"]["tts"] and boot["capabilities"]["ffmpeg"]
    assert client.get(base+"/api/settings").status_code==403
    for style in ("cinema","anime","ink","fantasy"):
        image=client.get(base+"/assets/styles/"+style+".jpg");image.raise_for_status();assert len(image.content)>1000
    headers={"Origin":base,"X-Studio-Token":boot["token"]}
    r=client.post(base+"/api/plan",headers=headers,json={"brief":"一叶小舟驶入晨雾中的水墨山谷。","style":"ink","ratio":"9:16","use_llm":False});r.raise_for_status()
    plan=r.json()
    for shot,line in zip(plan["shots"],["一叶小舟。","驶入山谷。","迎接晨光。"]):shot["narration"]=line
    r=client.post(base+"/api/jobs",headers=headers,json={"plan":plan,"mode":"preview","voice":"zf_001","idempotency":uuid.uuid4().hex,"paid_consent":False});r.raise_for_status()
    job_id=r.json()["id"];print("Cloud preview accepted",flush=True)
    start=time.monotonic()
    while time.monotonic()-start<420:
        r=client.get(base+"/api/jobs/"+job_id);r.raise_for_status();job=r.json()
        if job["status"]=="completed":break
        if job["status"] in {"failed","unknown"}:raise RuntimeError(job.get("message"))
        time.sleep(3)
    else:raise RuntimeError("Cloud preview timed out")
    result=client.get(base+"/api/jobs/"+job_id+"/file/video",headers={"Range":"bytes=0-1023"});assert result.status_code==206
    captions=client.get(base+"/api/jobs/"+job_id+"/file/subtitles");assert captions.status_code==200 and "小舟" in captions.text
    print("PASS: independent Linux CPU TTS + subtitles + 15s video; no paid generation",round(time.monotonic()-start,1),flush=True)
