"""Expiring, unguessable video-only links usable by a second device."""
import html
import io
import json
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from . import store

router = APIRouter()

def database():
    db = sqlite3.connect(store.DATA / "deliveries.sqlite3", timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS links(job TEXT PRIMARY KEY, token TEXT UNIQUE NOT NULL, expires REAL NOT NULL)")
    return db

def video(job_id):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(404, "作品不存在。")
    job = store.get_job(job_id)
    if not job or job["deleted"]:
        raise HTTPException(410, "作品已删除或已过保存期限。")
    path = store.JOBS / job_id / "final.mp4"
    if job["status"] != "completed" or not path.is_file():
        raise HTTPException(409, "成片尚未就绪。")
    return job, path

def public_origin(request):
    if request.url.hostname not in {"localhost", "127.0.0.1", "testserver"}:
        return "https://" + request.headers["host"]
    for filename in ("cloud-deployment.json", "sharing-state.json"):
        path = store.DATA / filename
        if not path.exists():
            continue
        state = json.loads(path.read_text(encoding="utf-8"))
        usable = state.get("ready") if filename.startswith("cloud") else state.get("online") and time.time()-state.get("checked_at",0)<120
        url = urlsplit(state.get("url") or "")
        if usable and url.scheme == "https" and url.hostname and not url.username and not url.password:
            return "https://" + url.netloc
    raise HTTPException(409, "请先开启对外分享或完成云端部署，才能生成手机可访问的二维码。")

def create(job_id, origin):
    job, _ = video(job_id)
    expires = min(time.time()+86400, job["created"]+float(store.settings()["retention_hours"])*3600)
    if expires <= time.time():
        raise HTTPException(410, "作品已过保存期限。")
    db = database()
    try:
        with db:
            db.execute("DELETE FROM links WHERE expires<=?", (time.time(),))
            db.execute("INSERT OR IGNORE INTO links VALUES(?,?,?)", (job_id,secrets.token_urlsafe(32),expires))
            row = db.execute("SELECT * FROM links WHERE job=?", (job_id,)).fetchone()
    finally:
        db.close()
    url = origin + "/d/" + row["token"]
    return {"url":url,"qr_url":f"/api/jobs/{job_id}/delivery/qr","expires":row["expires"],"temporary_host":origin.endswith((".trycloudflare.com",".lhr.life",".localhost.run"))}

def resolve(token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise HTTPException(404, "下载链接不存在。")
    db = database()
    try:
        row = db.execute("SELECT * FROM links WHERE token=?", (token,)).fetchone()
    finally:
        db.close()
    if not row:
        raise HTTPException(404, "下载链接不存在。")
    if row["expires"] <= time.time():
        raise HTTPException(410, "二维码已过期，请在创作页面重新获取。")
    return video(row["job"])

HEADERS = {"Cache-Control":"no-store", "Referrer-Policy":"no-referrer", "X-Robots-Tag":"noindex, nofollow", "Content-Security-Policy":"default-src 'self'; frame-ancestors 'none'; base-uri 'none'"}

@router.get("/d/{token}")
def landing(token):
    job, _ = resolve(token)
    title = html.escape(job["payload"]["plan"]["title"])
    return HTMLResponse(f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>扫码领取短片</title><link rel="stylesheet" href="/delivery.css"><main><h1>你的短片已完成</h1><p>{title}</p><video controls playsinline preload="metadata" src="/d/{token}/video"></video><a class="save" href="/d/{token}/video?download=true" download>保存 MP4 到手机</a><p>若微信内无法保存，请选择“在浏览器打开”后下载。链接有时效，请及时保存。</p></main></html>', headers=HEADERS)

@router.get("/d/{token}/video")
def download(token, download:bool=False):
    _, path = resolve(token)
    return FileResponse(path, media_type="video/mp4",filename="映刻短片.mp4" if download else None, headers=HEADERS)

@router.get("/d/{token}/qr.png")
def qr(token, request:Request):
    resolve(token)
    url = public_origin(request) + "/d/" + token
    return qr_image(url)

def qr_image(url):
    import qrcode
    output = io.BytesIO()
    qrcode.make(url, box_size=8, border=4).save(output,format="PNG")
    return Response(output.getvalue(),media_type="image/png",headers=HEADERS)
