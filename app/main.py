from __future__ import annotations
import base64, io, json, logging, os, queue, re, secrets, shutil, threading, time, uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
import httpx
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from PIL import Image, ImageOps, UnidentifiedImageError
from . import store, providers, media

TOKEN=secrets.token_urlsafe(32)
TASKS=queue.Queue()
STOP=threading.Event()
log=logging.getLogger("studio")
ID_RE=re.compile(r"^[a-f0-9]{32}$")

def valid_id(value):
    if not ID_RE.fullmatch(value): raise HTTPException(400,"编号格式不正确。")
    return value

def configuration():
    try: return store.settings()
    except Exception: raise HTTPException(500,"无法读取本机配置。请使用原 Windows 账户或恢复配置。")

def capabilities():
    cfg=configuration()
    voices_path=media.TTS_ROOT/"models/kokoro-v1.1-zh/voices"
    voices=[x.stem for x in voices_path.glob("*.pt")]
    preferred=["zf_001","zf_003","zm_010","zm_009"]
    choices=[v for v in preferred if v in voices] or voices[:4]
    return {"ffmpeg":media.FFMPEG.exists() and media.FFPROBE.exists(),
            "tts":media.TTS_PYTHON.exists() and bool(voices),
            "kling":providers.has_credentials(cfg),
            "llm":bool(cfg["llm_key"] and cfg["llm_model"]),
            "voices":choices,"data_directory":str(store.DATA),"local_only":True}

def public_job(job,detail=False):
    result={k:job[k] for k in ("id","created","updated","status","phase","message","mode","provider_id","error")}
    p=job["payload"]; result.update(title=p["plan"]["title"],ratio=p["plan"]["ratio"],style=p["plan"]["style"])
    result["mode_label"]="AI 视频" if job["mode"]=="kling" else "本地分镜预演"
    result["duration"]=15
    result["cover_url"]=f"/api/jobs/{job['id']}/file/cover" if (store.JOBS/job["id"]/"cover.jpg").exists() else None
    if job["status"]=="completed": result["video_url"]=f"/api/jobs/{job['id']}/file/video"
    if detail: result["payload"]=p; result["events"]=store.events(job["id"])
    return result

def progress(job_id,phase,message):
    store.update(job_id,status="running",phase=phase,message=message)

def process(job_id):
    job=store.get_job(job_id)
    if not job or job["deleted"] or job["status"]=="completed": return
    cfg=store.settings(); folder=store.JOBS/job_id; folder.mkdir(exist_ok=True)
    try:
        progress(job_id,"generating","正在准备三镜头预演" if job["mode"]=="preview" else "正在连接可灵视频服务")
        if job["mode"]=="kling" and not (folder/"source.mp4").exists():
            if not providers.has_credentials(cfg):
                raise providers.ProviderError("请先在服务配置中填写可灵开放平台凭证。")
            task_id=job["provider_id"]
            reference_id=job["payload"].get("reference_id")
            if not task_id:
                if job["submission_started"]: raise providers.SubmissionUnknown("任务已经提交过但没有收到任务号，请核对可灵控制台。")
                reference=None
                if reference_id:
                    with Image.open(store.UPLOADS/(reference_id+".jpg")) as original:
                        size=(720,1280) if job["payload"]["plan"]["ratio"]=="9:16" else (1280,720)
                        cropped=ImageOps.fit(original.convert("RGB"),size,method=Image.Resampling.LANCZOS)
                        cropped.save(folder/"provider-reference.jpg",quality=94)
                    reference=base64.b64encode((folder/"provider-reference.jpg").read_bytes()).decode()
                store.update(job_id,submission_started=1,message="已预留本次任务，正在提交可灵")
                task_id=providers.submit_kling(job["payload"]["plan"],cfg,reference,job_id)
                store.update(job_id,provider_id=task_id,message="已获得可灵任务号，正在等待生成")
                job=store.get_job(job_id)
            errors=0; began=time.monotonic()
            while not STOP.is_set():
                try:
                    result=providers.poll_kling(task_id,bool(reference_id),cfg); errors=0
                except (httpx.TransportError,providers.ProviderError):
                    errors+=1
                    if errors>=5:
                        store.update(job_id,status="paused",phase="generating",message="查询服务暂时不可用。任务号已保留，请点击继续查询。")
                        return
                    STOP.wait(min(5*errors,20)); continue
                state=result.get("task_status",result.get("status"))
                if state in {"succeed","succeeded","completed"}:
                    url=providers.video_url(result)
                    if not url: raise providers.ProviderError("可灵任务成功但没有可下载的视频地址。")
                    progress(job_id,"generating","画面已生成，正在下载源视频")
                    providers.download_video(url,folder/"source.tmp.mp4")
                    os.replace(folder/"source.tmp.mp4",folder/"source.mp4"); break
                if state in {"failed","cancelled"}:
                    raise providers.ProviderError("可灵生成失败，请在可灵控制台查看原因；平台没有自动重试扣费。")
                if time.monotonic()-began>1800:
                    store.update(job_id,status="paused",phase="generating",message="生成仍未完成。任务已保留，可稍后继续查询。")
                    return
                STOP.wait(10)
            if STOP.is_set(): return
        media.build_video(store.get_job(job_id),cfg,lambda phase,message:progress(job_id,phase,message))
        store.update(job_id,status="completed",phase="completed",message="短片已完成，可以预览和下载",error=None)
    except providers.SubmissionUnknown as exc:
        store.update(job_id,status="unknown",phase="unknown",message=str(exc),error="submission_unknown")
    except Exception as exc:
        message=str(exc) if isinstance(exc,(providers.ProviderError,RuntimeError)) else "处理未完成，请查看本机服务日志。"
        log.exception("Job %s failed",job_id)
        store.update(job_id,status="failed",phase="failed",message=message,error=type(exc).__name__)

def cleanup():
    cfg=store.settings(); cutoff=time.time()-cfg["retention_hours"]*3600
    with store.connection() as db:
        rows=db.execute("SELECT id FROM jobs WHERE created<? AND status IN ('completed','failed','cancelled') AND deleted=0",(cutoff,)).fetchall()
    for row in rows:
        store.update(row["id"],deleted=1)
        shutil.rmtree(store.JOBS/row["id"],ignore_errors=True)
    with store.connection() as db:
        refs={json.loads(r[0]).get("reference_id") for r in db.execute("SELECT payload FROM jobs WHERE deleted=0")}
    for upload in store.UPLOADS.glob("*.jpg"):
        if upload.stem not in refs and upload.stat().st_mtime<cutoff: upload.unlink(missing_ok=True)

def worker():
    last_cleanup=0
    while not STOP.is_set():
        try:
            if time.monotonic()-last_cleanup>3600:
                cleanup(); last_cleanup=time.monotonic()
            job_id=TASKS.get(timeout=1)
        except queue.Empty: continue
        except Exception:
            log.exception("Cleanup failed"); last_cleanup=time.monotonic(); continue
        try: process(job_id)
        finally: TASKS.task_done()

@asynccontextmanager
async def lifespan(app):
    STOP.clear(); store.init_db()
    for job_id in store.recover(): TASKS.put(job_id)
    thread=threading.Thread(target=worker,name="studio-media-worker",daemon=True); thread.start()
    yield
    STOP.set()
    thread.join(timeout=3)

app=FastAPI(title="映刻 AIGC 创作体验平台",lifespan=lifespan,docs_url=None,redoc_url=None)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=["127.0.0.1","localhost","testserver"])

@app.middleware("http")
async def local_security(request,call_next):
    if request.method not in {"GET","HEAD","OPTIONS"}:
        origin=request.headers.get("origin")
        if origin and urlparse(origin).netloc!=request.headers.get("host"):
            return __import__("starlette.responses",fromlist=["JSONResponse"]).JSONResponse({"detail":"跨站请求已拒绝。"},403)
        if not secrets.compare_digest(request.headers.get("x-studio-token",""),TOKEN):
            return __import__("starlette.responses",fromlist=["JSONResponse"]).JSONResponse({"detail":"会话已更新，请刷新页面。"},403)
    response=await call_next(request)
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Referrer-Policy"]="same-origin"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Content-Security-Policy"]="default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    if request.url.path.startswith("/api/"): response.headers["Cache-Control"]="no-store"
    return response

class PlanInput(BaseModel):
    brief:str=Field(min_length=4,max_length=300)
    style:str="cinema"
    ratio:str="9:16"
    use_llm:bool=False
    send_consent:bool=False

class JobInput(BaseModel):
    plan:dict
    mode:str="preview"
    reference_id:str|None=None
    voice:str="zf_001"
    idempotency:str=Field(min_length=16,max_length=80)
    paid_consent:bool=False

class ResumeInput(BaseModel):
    provider_id:str|None=None

class SettingsInput(BaseModel):
    kling_base:str=store.DEFAULTS["kling_base"]
    kling_model:str="kling-v3"
    kling_mode:str="std"
    kling_api_key:str=Field(default="",max_length=4096)
    kling_access_key:str=Field(default="",max_length=500)
    kling_secret_key:str=Field(default="",max_length=500)
    llm_base:str=store.DEFAULTS["llm_base"]
    llm_model:str=Field(default="",max_length=100)
    llm_key:str=Field(default="",max_length=500)
    daily_limit:int=Field(default=10,ge=1,le=100)
    tts_device:str="cuda"
    retention_hours:int=Field(default=72,ge=1,le=720)

@app.get("/api/bootstrap")
def bootstrap():
    return {"token":TOKEN,"capabilities":capabilities(),"version":"0.1.0","retention_hours":configuration()["retention_hours"]}

@app.post("/api/plan")
def plan(body:PlanInput):
    if body.style not in providers.STYLE or body.ratio not in {"9:16","16:9"}: raise HTTPException(400,"画风或画幅不正确。")
    cfg=configuration()
    try:
        if body.use_llm:
            if not body.send_consent: raise HTTPException(400,"请先确认向文本模型发送创意。")
            if not cfg["llm_key"] or not cfg["llm_model"]: raise HTTPException(400,"请先配置文本模型。")
            return providers.plan_with_llm(body.brief,body.style,body.ratio,cfg)
        return providers.make_template(body.brief,body.style,body.ratio)
    except providers.ProviderError as exc: raise HTTPException(502,str(exc))
    except httpx.HTTPError: raise HTTPException(502,"文本模型暂时无法连接，请核对网络和服务地址。")

@app.post("/api/uploads")
async def upload(image:UploadFile=File(...)):
    raw=await image.read(10*1024*1024+1)
    if len(raw)>10*1024*1024: raise HTTPException(413,"图片不能超过 10 MB。")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.width*im.height>40_000_000: raise HTTPException(400,"图片像素过大，请缩小后上传。")
            normalized=ImageOps.exif_transpose(im).convert("RGB")
            normalized.thumbnail((1920,1920))
            image_id=uuid.uuid4().hex
            normalized.save(store.UPLOADS/(image_id+".jpg"),quality=92)
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError):
        raise HTTPException(400,"请选择可读取的 JPG、PNG 或 WebP 图片。")
    return {"id":image_id,"url":"/api/uploads/"+image_id}

@app.get("/api/uploads/{image_id}")
def uploaded_image(image_id:str):
    path=store.UPLOADS/(valid_id(image_id)+".jpg")
    if not path.exists(): raise HTTPException(404,"参考图不存在。")
    return FileResponse(path,media_type="image/jpeg")

@app.get("/api/jobs")
def jobs(): return {"jobs":[public_job(j) for j in store.list_jobs()]}

@app.get("/api/jobs/{job_id}")
def get_job(job_id:str):
    job=store.get_job(valid_id(job_id))
    if not job: raise HTTPException(404,"任务不存在或已删除。")
    return public_job(job,detail=True)

@app.post("/api/jobs")
def create_job(body:JobInput):
    if body.mode not in {"preview","kling"}: raise HTTPException(400,"生成模式不正确。")
    caps=capabilities(); cfg=configuration()
    if not caps["tts"] or not caps["ffmpeg"]: raise HTTPException(400,"本地配音或视频合成工具不可用，请查看服务配置。")
    if body.voice not in caps["voices"]: raise HTTPException(400,"所选音色不可用。")
    if body.reference_id and not (store.UPLOADS/(valid_id(body.reference_id)+".jpg")).exists(): raise HTTPException(400,"请重新上传参考图。")
    if body.mode=="kling":
        if not caps["kling"]: raise HTTPException(400,"请先配置可灵开放平台凭证。")
        if not body.paid_consent: raise HTTPException(400,"请确认本次付费生成及素材外发。")
    try: validated=providers.validate_plan(body.plan)
    except providers.ProviderError as exc: raise HTTPException(400,str(exc))
    style=body.plan.get("style"); ratio=body.plan.get("ratio")
    if style not in providers.STYLE or ratio not in {"9:16","16:9"}: raise HTTPException(400,"分镜画风或画幅不正确。")
    validated.update(style=style,ratio=ratio,brief=str(body.plan.get("brief",""))[:300],
                     planner=body.plan.get("planner","template"),planner_label=body.plan.get("planner_label","分镜"))
    payload={"plan":validated,"voice":body.voice,"reference_id":body.reference_id,"paid_consent":body.paid_consent}
    try: job,new=store.create_job(payload,body.mode,body.idempotency,cfg["daily_limit"])
    except ValueError as exc: raise HTTPException(409,str(exc))
    if new: TASKS.put(job["id"])
    return public_job(job,True)

@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id:str,body:ResumeInput):
    job=store.get_job(valid_id(job_id))
    if not job: raise HTTPException(404,"任务不存在。")
    if job["status"] not in {"failed","paused","unknown"}: raise HTTPException(409,"这个任务不需要恢复。")
    if job["mode"]=="kling":
        if job["status"]=="unknown":
            if not body.provider_id or not re.fullmatch(r"[a-zA-Z0-9_-]{1,200}",body.provider_id): raise HTTPException(400,"请先填写可灵控制台确认的原任务号。")
            store.update(job_id,provider_id=body.provider_id)
        elif not job["provider_id"]: raise HTTPException(409,"没有已确认的可灵任务号，无法安全恢复。请核对控制台。")
    store.update(job_id,status="queued",phase="queued",error=None,message="已保留已有素材，正在继续处理")
    TASKS.put(job_id); return {"ok":True}

@app.delete("/api/jobs/{job_id}")
def delete_job(job_id:str):
    job=store.get_job(valid_id(job_id))
    if not job: raise HTTPException(404,"任务不存在。")
    if job["status"] not in store.TERMINAL|{"paused"}: raise HTTPException(409,"任务正在制作，请完成后再删除。")
    store.update(job_id,deleted=1)
    shutil.rmtree(store.JOBS/job_id,ignore_errors=True)
    return {"ok":True}

@app.get("/api/jobs/{job_id}/file/{kind}")
def artifact(job_id:str,kind:str,download:bool=False):
    job=store.get_job(valid_id(job_id))
    names={"video":("final.mp4","video/mp4"),"cover":("cover.jpg","image/jpeg"),
           "subtitles":("subtitles.srt","application/x-subrip"),"storyboard":("storyboard.json","application/json")}
    if not job or kind not in names: raise HTTPException(404,"文件不存在。")
    if kind!="cover" and job["status"]!="completed": raise HTTPException(409,"成片尚未完成。")
    name,mime=names[kind]; path=store.JOBS/job_id/name
    if not path.exists(): raise HTTPException(404,"文件已被清理。")
    title=re.sub(r'[<>:"/\\|?*\x00-\x1f]',"_",job["payload"]["plan"]["title"])
    filename=title+Path(name).suffix if download else None
    return FileResponse(path,media_type=mime,filename=filename)

@app.get("/api/settings")
def get_settings():
    cfg=configuration()
    public={key:cfg[key] for key in store.DEFAULTS}
    public.update({key+"_configured":bool(cfg[key]) for key in store.SECRETS})
    return {"settings":public,"capabilities":capabilities()}

@app.put("/api/settings")
def set_settings(body:SettingsInput):
    try:
        values=body.model_dump()
        api_key=values["kling_api_key"].strip()
        if api_key.lower().startswith("bearer "):
            api_key=api_key[7:].strip()
        if api_key and any(c.isspace() for c in api_key):
            raise ValueError("API Key 不能包含空格或换行，请只复制密钥本身。")
        values["kling_api_key"]=api_key
        values["kling_base"]=providers.validate_base(values["kling_base"])
        values["llm_base"]=providers.validate_base(values["llm_base"])
        if values["tts_device"] not in {"cpu","cuda"} or values["kling_mode"] not in {"std","pro"}:
            raise ValueError("请选择有效的配音设备或视频档位。")
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}",values["kling_model"]): raise ValueError("模型名称不正确。")
        store.save_settings(values)
    except (ValueError,RuntimeError) as exc: raise HTTPException(400,str(exc))
    return get_settings()

@app.post("/api/settings/check-kling")
def check_connection():
    cfg=configuration()
    if not providers.has_credentials(cfg): raise HTTPException(400,"请先保存可灵凭证。")
    try: return providers.check_kling(cfg)
    except (providers.ProviderError,httpx.HTTPError) as exc:
        raise HTTPException(502,str(exc) if isinstance(exc,providers.ProviderError) else "无法连接可灵，请检查网络和 API 地区。")

app.mount("/",StaticFiles(directory=store.ROOT/"static",html=True),name="ui")
