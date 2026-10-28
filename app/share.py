"""A separate visitor gateway. The administrator studio stays on localhost:8787."""
from __future__ import annotations
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .store import ROOT, DATA, JOBS, UPLOADS, protect

CORE = "http://127.0.0.1:8787"
DB = DATA / "share.sqlite3"
SECRET_FILE = DATA / "share-secret.json"
LOCK = threading.RLock()
DAILY_LIMIT = int(os.environ.get("STUDIO_SHARE_DAILY_LIMIT", "10"))
GUEST_AI_LIMIT = 1
COOKIE = "yingke_guest"


@contextmanager
def db():
    handle = sqlite3.connect(DB, timeout=20)
    handle.row_factory = sqlite3.Row
    try:
        handle.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS uploads (id TEXT PRIMARY KEY, owner TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reservations (
          key TEXT PRIMARY KEY, owner TEXT NOT NULL, created REAL NOT NULL,
          mode TEXT NOT NULL, digest TEXT NOT NULL, job_id TEXT, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts (ip TEXT NOT NULL, at REAL NOT NULL);
        """)
        yield handle
        handle.commit()
    except Exception:
        handle.rollback()
        raise
    finally:
        handle.close()


def share_code():
    with LOCK:
        if os.environ.get("STUDIO_SHARE_CODE"):
            return os.environ["STUDIO_SHARE_CODE"]
        if SECRET_FILE.exists():
            return protect(json.loads(SECRET_FILE.read_text(encoding="utf-8"))["code"], decrypt=True)
        code = secrets.token_urlsafe(18)
        SECRET_FILE.write_text(json.dumps({"code": protect(code)}, indent=2), encoding="utf-8")
        return code


def visitor(request: Request):
    raw = request.cookies.get(COOKIE, "")
    if not raw:
        raise HTTPException(401, "请先输入主办方提供的体验码。")
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with db() as handle:
        row = handle.execute("SELECT * FROM sessions WHERE id=? AND expires>?", (digest, time.time())).fetchone()
    if not row:
        raise HTTPException(401, "体验会话已过期，请重新打开分享链接。")
    return dict(row)


async def core(method, path, *, body=None, files=None, params=None):
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            headers = {}
            if method not in {"GET", "HEAD"}:
                token = (await client.get(CORE + "/api/bootstrap")).json()["token"]
                headers["X-Studio-Token"] = token
                headers["Origin"] = CORE
            response = await client.request(method, CORE + path, headers=headers, json=body, files=files, params=params)
    except (httpx.HTTPError, KeyError, ValueError):
        raise HTTPException(503, "创作后台暂时离线，请稍后再试。")
    try:
        value = response.json()
    except ValueError:
        raise HTTPException(502, "创作后台暂时无法响应。")
    if response.status_code >= 400:
        raise HTTPException(response.status_code, value.get("detail", "请求未完成。"))
    return value


def owns_job(owner, job_id):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(404, "作品不存在。")
    with db() as handle:
        match = handle.execute("SELECT 1 FROM reservations WHERE owner=? AND job_id=?", (owner, job_id)).fetchone()
    if not match:
        raise HTTPException(404, "作品不存在或不属于当前体验会话。")


def owns_upload(owner, upload_id):
    with db() as handle:
        match = handle.execute("SELECT 1 FROM uploads WHERE id=? AND owner=?", (upload_id, owner)).fetchone()
    if not match:
        raise HTTPException(404, "请使用自己上传的参考图。")


app = FastAPI(title="映刻访客体验", docs_url=None, redoc_url=None, openapi_url=None)
SHARE_HOSTS = ["127.0.0.1", "localhost", "testserver", "*.trycloudflare.com", "*.lhr.life", "*.localhost.run"]
SHARE_HOSTS += [h.strip() for h in os.environ.get("STUDIO_PUBLIC_HOSTS", "").split(",") if h.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=SHARE_HOSTS)


@app.middleware("http")
async def guest_security(request, call_next):
    path = request.url.path
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "跨站请求已拒绝。"}, 403)
    if path.startswith("/api/") and path not in {"/api/share/login", "/api/share/status", "/api/share/ping"}:
        try:
            session = visitor(request)
            if request.method not in {"GET", "HEAD"} and not secrets.compare_digest(session["csrf"], request.headers.get("x-studio-token", "")):
                raise HTTPException(403, "会话已更新，请刷新页面。")
            request.state.visitor = session
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, exc.status_code)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class Login(BaseModel):
    code: str = Field(min_length=4, max_length=200)


@app.post("/api/share/login")
def login(body: Login, request: Request):
    ip = hashlib.sha256((request.client.host if request.client else "unknown").encode()).hexdigest()
    with LOCK, db() as handle:
        handle.execute("DELETE FROM attempts WHERE at<?", (time.time() - 60,))
        count = handle.execute("SELECT count(*) FROM attempts WHERE ip=?", (ip,)).fetchone()[0]
        if count >= 10:
            raise HTTPException(429, "尝试次数较多，请一分钟后重试。")
        handle.execute("INSERT INTO attempts(ip,at) VALUES(?,?)", (ip, time.time()))
    if not secrets.compare_digest(body.code, share_code()):
        raise HTTPException(401, "体验码不正确，请重新打开主办方分享的链接。")
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    csrf = secrets.token_urlsafe(32)
    with db() as handle:
        handle.execute("INSERT INTO sessions(id,csrf,expires) VALUES(?,?,?)", (digest, csrf, time.time() + 7 * 86400))
    response = JSONResponse({"ok": True})
    public_host = request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}
    response.set_cookie(COOKIE, raw, max_age=7 * 86400, httponly=True, secure=public_host or request.url.scheme == "https", samesite="lax")
    return response


@app.get("/api/share/status")
def share_status(request: Request):
    try:
        visitor(request)
        authorized = True
    except HTTPException:
        authorized = False
    return {"shared": True, "authorized": authorized, "guest_ai_limit": GUEST_AI_LIMIT, "daily_limit": DAILY_LIMIT}


@app.get("/api/share/ping")
async def ping():
    try:
        await core("GET", "/api/bootstrap")
        online = True
    except HTTPException:
        online = False
    return JSONResponse({"online": online}, headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})


@app.get("/api/bootstrap")
async def bootstrap(request: Request):
    value = await core("GET", "/api/bootstrap")
    capabilities = {k: value["capabilities"][k] for k in ("ffmpeg", "tts", "kling", "voices")}
    capabilities.update(llm=False, local_only=False)
    return {"token": request.state.visitor["csrf"], "capabilities": capabilities, "version": "0.1.0-share", "retention_hours": value["retention_hours"]}


@app.post("/api/plan")
async def plan(body: dict):
    if body.get("use_llm"):
        raise HTTPException(400, "体验版暂未开放额外的文本模型服务。")
    return await core("POST", "/api/plan", body=body)


@app.post("/api/uploads")
async def upload(request: Request, image: UploadFile = File(...)):
    raw = await image.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "图片不能超过10 MB。")
    value = await core("POST", "/api/uploads", files={"image": ("reference", raw, image.content_type)})
    with db() as handle:
        handle.execute("INSERT INTO uploads(id,owner) VALUES(?,?)", (value["id"], request.state.visitor["id"]))
    return value


@app.get("/api/uploads/{upload_id}")
def uploaded(upload_id: str, request: Request):
    owns_upload(request.state.visitor["id"], upload_id)
    if not re.fullmatch(r"[a-f0-9]{32}", upload_id):
        raise HTTPException(404, "图片不存在。")
    path = UPLOADS / (upload_id + ".jpg")
    if not path.exists():
        raise HTTPException(404, "图片已清理。")
    return FileResponse(path, media_type="image/jpeg")


@app.post("/api/jobs")
async def create_job(body: dict, request: Request):
    owner = request.state.visitor["id"]
    mode = body.get("mode", "preview")
    if mode not in {"kling", "preview"}:
        raise HTTPException(400, "制作方式不正确。")
    key = str(body.get("idempotency", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", key):
        raise HTTPException(400, "请求编号不正确，请刷新页面。")
    if body.get("reference_id"):
        owns_upload(owner, body["reference_id"])
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    namespaced = "share-" + owner[:16] + "-" + key
    with LOCK, db() as handle:
        handle.execute("BEGIN IMMEDIATE")
        old = handle.execute("SELECT * FROM reservations WHERE key=?", (namespaced,)).fetchone()
        if old and old["digest"] != fingerprint:
            raise HTTPException(409, "这个请求已用于其他内容，请发起新创作。")
        if not old:
            cutoff = time.time() - 86400
            guest = handle.execute("SELECT count(*) FROM reservations WHERE owner=? AND mode=? AND created>? AND state!='rejected'", (owner, mode, cutoff)).fetchone()[0]
            maximum = GUEST_AI_LIMIT if mode == "kling" else 3
            if guest >= maximum:
                raise HTTPException(429, "你今天的体验次数已用完，明天可以继续创作。")
            total = handle.execute("SELECT count(*) FROM reservations WHERE mode='kling' AND created>? AND state!='rejected'", (cutoff,)).fetchone()[0]
            if mode == "kling" and total >= DAILY_LIMIT:
                raise HTTPException(429, "今天的活动制作名额已用完，请联系主办方。")
            handle.execute("INSERT INTO reservations(key,owner,created,mode,digest,state) VALUES(?,?,?,?,?,'reserved')", (namespaced, owner, time.time(), mode, fingerprint))
        known = old["job_id"] if old else None
    if known:
        return await core("GET", "/api/jobs/" + known)
    forwarded = dict(body)
    forwarded["idempotency"] = namespaced
    try:
        value = await core("POST", "/api/jobs", body=forwarded)
    except HTTPException as exc:
        if exc.status_code < 500:
            with db() as handle:
                handle.execute("UPDATE reservations SET state='rejected' WHERE key=?", (namespaced,))
        raise
    with db() as handle:
        handle.execute("UPDATE reservations SET job_id=?,state='accepted' WHERE key=?", (value["id"], namespaced))
    return value


@app.get("/api/jobs")
async def jobs(request: Request):
    with db() as handle:
        owned = {r[0] for r in handle.execute("SELECT job_id FROM reservations WHERE owner=?", (request.state.visitor["id"],))}
    value = await core("GET", "/api/jobs")
    return {"jobs": [j for j in value["jobs"] if j["id"] in owned]}


@app.get("/api/jobs/{job_id}")
async def job(job_id: str, request: Request):
    owns_job(request.state.visitor["id"], job_id)
    return await core("GET", "/api/jobs/" + job_id)


@app.post("/api/jobs/{job_id}/resume")
async def resume(job_id: str, body: dict, request: Request):
    owns_job(request.state.visitor["id"], job_id)
    if body.get("provider_id"):
        raise HTTPException(403, "待核对的付费任务需要由主办方在管理员工作台处理。")
    return await core("POST", "/api/jobs/" + job_id + "/resume", body={"provider_id": None})


@app.delete("/api/jobs/{job_id}")
async def delete(job_id: str, request: Request):
    owns_job(request.state.visitor["id"], job_id)
    return await core("DELETE", "/api/jobs/" + job_id)


@app.get("/api/jobs/{job_id}/file/{kind}")
async def artifact(job_id: str, kind: str, request: Request, download: bool = False):
    owns_job(request.state.visitor["id"], job_id)
    names = {"video": ("final.mp4", "video/mp4"), "cover": ("cover.jpg", "image/jpeg"), "subtitles": ("subtitles.srt", "application/x-subrip"), "storyboard": ("storyboard.json", "application/json")}
    if kind not in names:
        raise HTTPException(404, "文件不存在。")
    info = await core("GET", "/api/jobs/" + job_id)
    if kind != "cover" and info["status"] != "completed":
        raise HTTPException(409, "成片尚未完成。")
    name, mime = names[kind]
    path = JOBS / job_id / name
    if not path.exists():
        raise HTTPException(404, "文件已被清理。")
    return FileResponse(path, media_type=mime, filename=("映刻短片" + Path(name).suffix) if download else None)


@app.api_route("/api/settings", methods=["GET", "PUT", "POST", "DELETE"])
@app.api_route("/api/settings/{rest:path}", methods=["GET", "PUT", "POST", "DELETE"])
def no_admin(rest: str = ""):
    raise HTTPException(403, "访客入口不提供管理员服务配置。")


@app.get("/")
def index():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    html = html.replace('<script src="/app.js" defer>', '<link rel="stylesheet" href="/share.css"><script src="/share-client.js" defer></script><script src="/app.js" defer>')
    html = html.replace('id="navSettings"', 'id="navSettings" hidden')
    html = html.replace("本机工作室", "活动体验工作室").replace("本地创作者", "体验创作者").replace("作品保存在这台电脑", "独立的创作与作品空间").replace("本机体验版", "分享体验版")
    html = html.replace("同意将创意和参考图发送至可灵，并按开放平台价格消耗本次生成额度。", "同意将创意和参考图发送至可灵，本次制作使用主办方提供的活动额度。")
    return HTMLResponse(html)


app.mount("/", StaticFiles(directory=ROOT / "static"), name="visitor-ui")
