"""Local, transactional storage. Secrets are encrypted for the current Windows user."""
from __future__ import annotations
import base64, ctypes, json, os, sqlite3, threading, time, uuid
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("STUDIO_DATA_DIR", str(ROOT / "data"))).resolve()
JOBS = DATA / "jobs"
UPLOADS = DATA / "uploads"
AUDIO_UPLOADS = DATA / "audio-uploads"
for folder in (DATA, JOBS, UPLOADS, AUDIO_UPLOADS, ROOT / "work"):
    folder.mkdir(parents=True, exist_ok=True)
DB = DATA / "studio.sqlite3"
CONFIG = DATA / "settings.json"
LOCK = threading.RLock()
DEFAULTS = {
    "kling_base": "https://api-beijing.klingai.com/v1",
    "kling_model": "kling-v3", "kling_mode": "std",
    "llm_base": "https://api.openai.com/v1", "llm_model": "",
    "daily_limit": 10, "tts_device": "cuda" if os.name == "nt" else "cpu", "retention_hours": 72,
}
SECRETS = ("kling_api_key", "kling_access_key", "kling_secret_key", "llm_key")
TERMINAL = {"completed", "failed", "cancelled", "unknown"}

class Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_byte))]

def protect(text: str, decrypt=False) -> str:
    if not text:
        return ""
    master = os.environ.get("STUDIO_MASTER_KEY", "")
    if text.startswith("fernet:") or (not decrypt and (master or os.name != "nt")):
        if not master:
            raise RuntimeError("云端需要配置 STUDIO_MASTER_KEY，以加密保护服务密钥。")
        from cryptography.fernet import Fernet
        cipher = Fernet(master.encode("ascii"))
        if decrypt:
            return cipher.decrypt(text.removeprefix("fernet:").encode("ascii")).decode("utf-8")
        return "fernet:" + cipher.encrypt(text.encode("utf-8")).decode("ascii")
    if os.name != "nt":
        raise RuntimeError("Windows 本机凭证不能直接迁移，请在云平台环境变量中重新配置。")
    raw = base64.b64decode(text) if decrypt else text.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise RuntimeError("Windows 密钥保护失败，请使用保存配置时的 Windows 账户。")
    try:
        result = ctypes.string_at(target.data, target.size)
        return result.decode("utf-8") if decrypt else base64.b64encode(result).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)

def settings():
    with LOCK:
        result = dict(DEFAULTS)
        if CONFIG.exists():
            saved = json.loads(CONFIG.read_text(encoding="utf-8"))
            for key in SECRETS:
                saved[key] = protect(saved.get(key, ""), decrypt=True)
            result.update(saved)
        for key in SECRETS:
            result.setdefault(key, "")
            if os.environ.get("STUDIO_" + key.upper()):
                result[key] = os.environ["STUDIO_" + key.upper()]
        for key in ("kling_base", "kling_model", "kling_mode", "tts_device"):
            if os.environ.get("STUDIO_" + key.upper()):
                result[key] = os.environ["STUDIO_" + key.upper()]
        return result

def save_settings(changes):
    with LOCK:
        current = settings()
        for key, value in changes.items():
            if key in SECRETS:
                if value == "__DELETE__":
                    current[key] = ""
                elif value:
                    current[key] = value.strip()
            elif key in DEFAULTS:
                current[key] = value
        encrypted = dict(current)
        for key in SECRETS:
            encrypted[key] = protect(current[key])
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(encrypted, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG)
        return current

@contextmanager
def connection():
    db = sqlite3.connect(DB, timeout=20)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_db():
    with connection() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, idempotency TEXT UNIQUE NOT NULL,
            created REAL NOT NULL, updated REAL NOT NULL,
            status TEXT NOT NULL, phase TEXT NOT NULL, message TEXT NOT NULL,
            mode TEXT NOT NULL, payload TEXT NOT NULL,
            provider_id TEXT, submission_started INTEGER NOT NULL DEFAULT 0,
            error TEXT, deleted INTEGER NOT NULL DEFAULT 0)""")
        db.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, at REAL NOT NULL,
            phase TEXT NOT NULL, message TEXT NOT NULL)""")

def decode(row):
    if not row:
        return None
    value = dict(row)
    value["payload"] = json.loads(value["payload"])
    return value

def get_job(job_id, include_deleted=False):
    with connection() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=? AND (?=1 OR deleted=0)", (job_id, int(include_deleted))).fetchone()
        return decode(row)

def list_jobs():
    with connection() as db:
        return [decode(r) for r in db.execute("SELECT * FROM jobs WHERE deleted=0 ORDER BY created DESC LIMIT 80")]

def create_job(payload, mode, key, limit):
    with LOCK, connection() as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT * FROM jobs WHERE idempotency=?", (key,)).fetchone()
        if old:
            if old["deleted"]:
                raise ValueError("这个请求已删除，请发起一个新任务。")
            if json.loads(old["payload"]) != payload or old["mode"] != mode:
                raise ValueError("请求编号已被用于其他内容，请刷新后重试。")
            return decode(old), False
        active = db.execute("SELECT count(*) FROM jobs WHERE status NOT IN ('completed','failed','unknown','cancelled')").fetchone()[0]
        if active >= 4:
            raise ValueError("当前已有 4 个任务，请等待后再提交。")
        if mode == "kling":
            count = db.execute("SELECT count(*) FROM jobs WHERE mode='kling' AND created>?", (time.time()-86400,)).fetchone()[0]
            if count >= limit:
                raise ValueError("已达到最近 24 小时的 AI 任务上限，请调整服务配置。")
        job_id, now = uuid.uuid4().hex, time.time()
        db.execute("INSERT INTO jobs (id,idempotency,created,updated,status,phase,message,mode,payload) VALUES (?,?,?,?,?,?,?,?,?)",
                   (job_id,key,now,now,"queued","queued","已加入本机队列",mode,json.dumps(payload,ensure_ascii=False)))
        return decode(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()), True

def update(job_id, **changes):
    allowed = {"status","phase","message","provider_id","submission_started","error","deleted"}
    if not changes or not set(changes).issubset(allowed):
        raise ValueError("Invalid job update")
    with connection() as db:
        fields = ",".join(f"{key}=?" for key in changes)
        db.execute(f"UPDATE jobs SET {fields},updated=? WHERE id=?", (*changes.values(),time.time(),job_id))
        if "message" in changes:
            db.execute("INSERT INTO events(job_id,at,phase,message) VALUES(?,?,?,?)",
                       (job_id,time.time(),changes.get("phase","info"),changes["message"]))

def events(job_id):
    with connection() as db:
        return [dict(r) for r in db.execute("SELECT at,phase,message FROM events WHERE job_id=? ORDER BY id",(job_id,))]

def recover():
    with connection() as db:
        rows = db.execute("SELECT * FROM jobs WHERE deleted=0 AND status NOT IN ('completed','failed','unknown','cancelled')").fetchall()
    resume=[]
    for row in rows:
        if row["mode"]=="kling" and row["submission_started"] and not row["provider_id"]:
            update(row["id"],status="unknown",phase="unknown",message="上次提交结果未知。为避免重复扣费，已停止自动重提。请先在可灵控制台核对。")
        else:
            update(row["id"],status="queued",phase="queued",message="正在恢复之前的任务")
            resume.append(row["id"])
    return resume
