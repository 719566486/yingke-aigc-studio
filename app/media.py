from __future__ import annotations
import json, math, os, random, re, subprocess, threading, textwrap, wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
from .store import ROOT, JOBS, UPLOADS
FFMPEG = Path(os.environ.get("STUDIO_FFMPEG", r"D:\workspace\tools\ffmpeg\ffmpeg-8.1.2-essentials_build\bin\ffmpeg.exe"))
FFPROBE = FFMPEG.with_name("ffprobe.exe")
TTS_ROOT = Path(os.environ.get("STUDIO_TTS_ROOT", r"D:\workspace\local_tts"))
TTS_PYTHON = TTS_ROOT / ".venv/Scripts/python.exe"
TTS_LOCK = threading.Lock()
FONT = Path(r"C:\Windows\Fonts\msyh.ttc")
BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")
PALETTES = {"cinema":("#b49e85","#2d4349","#dfbfa0"),"anime":("#b6c4de","#557c82","#e3bdbe"),
            "ink":("#e2e4dc","#425d61","#becdc3"),"fantasy":("#cdb9e1","#68578d","#ebc899")}
def run(command,cwd,timeout=240):
    env=os.environ.copy()
    env.update(TEMP=str(ROOT/"work"),TMP=str(ROOT/"work"),PYTHONIOENCODING="utf-8",PYTHONDONTWRITEBYTECODE="1")
    flags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
    result=subprocess.run([str(x) for x in command],cwd=cwd,env=env,capture_output=True,timeout=timeout,creationflags=flags)
    if result.returncode:
        # Detailed stderr stays local, never echo possible provider URLs or keys to the browser.
        (Path(cwd)/"processing-error.log").write_bytes(result.stderr[-16000:])
        raise RuntimeError("本机媒体处理未完成，请检查任务目录中的 processing-error.log。")
    return result.stdout

def probe(path):
    result=run([FFPROBE,"-v","error","-show_format","-show_streams","-of","json",path],Path(path).parent)
    return json.loads(result)

def duration(path): return float(probe(path)["format"]["duration"])
def hexrgb(color): return tuple(int(color[i:i+2],16) for i in (1,3,5))
def font(size,bold=False): return ImageFont.truetype(str(BOLD if bold else FONT),size)
def wrap(draw,value,face,width):
    lines=[]; line=""
    for char in value:
        if char=="\n":
            lines.append(line); line=""; continue
        if draw.textlength(line+char,font=face)>width and line:
            lines.append(line); line=char
        else: line+=char
    if line: lines.append(line)
    return "\n".join(lines)

def make_card(plan,shot,path,reference=None):
    w,h=(720,1280) if plan["ratio"]=="9:16" else (1280,720)
    top,low,accent=[hexrgb(x) for x in PALETTES[plan["style"]]]
    image=Image.new("RGB",(w,h)); draw=ImageDraw.Draw(image)
    for y in range(h):
        t=y/h
        draw.line((0,y,w,y),fill=tuple(int(top[c]*(1-t)+low[c]*t) for c in range(3)))
    if reference:
        with Image.open(reference) as source:
            image=ImageOps.fit(ImageOps.exif_transpose(source).convert("RGB"),(w,h),method=Image.Resampling.LANCZOS)
        image=image.filter(ImageFilter.GaussianBlur(1))
        overlay=Image.new("RGBA",(w,h),(14,23,38,125)); image=Image.alpha_composite(image.convert("RGBA"),overlay).convert("RGB")
        draw=ImageDraw.Draw(image)
    else:
        rng=random.Random(shot["index"]+len(plan["title"]))
        draw.ellipse((w*.59,h*.16,w*.59+w*.18,h*.16+w*.18),fill=accent)
        for layer in range(4):
            y=h*(.48+layer*.09)
            points=[(0,h),(0,y)]
            for x in range(0,w+80,80): points.append((x,y+rng.randint(-100,100)))
            points.extend([(w,h)])
            col=tuple(max(0,int(low[c]*(.65+layer*.1))) for c in range(3))
            draw.polygon(points,fill=col)
        for _ in range(25):
            x=rng.randint(35,w-35); y=rng.randint(50,int(h*.45)); draw.ellipse((x,y,x+2,y+2),fill=(245,244,229))
    pad=int(w*.075)
    draw.text((pad,int(h*.06)),"映刻  /  本地分镜预演",font=font(20),fill="#ffffff")
    draw.text((pad,int(h*.12)),f"0{shot['index']}  /  {shot['name']}",font=font(24,True),fill="#f0ede6")
    title=wrap(draw,plan["title"],font(56,True),w-pad*2)
    draw.multiline_text((pad,int(h*.25)),title,font=font(56,True),fill="white",spacing=16)
    desc=wrap(draw,shot["visual"][:72],font(21),w-pad*2)
    draw.multiline_text((pad,int(h*.62)),desc,font=font(21),fill="#e5e7e5",spacing=12)
    draw.text((pad,h-75),"你的灵感  ·  三镜头预演  ·  非AI生成画面",font=font(16),fill="#d9dedc")
    image.save(path,quality=94)

def srt_time(seconds):
    ms=round(seconds*1000); return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}"

def write_subtitle(path,shot,w,h):
    # Exact text is overlaid here, independently from the video generation model.
    text=shot["narration"].replace("\\","＼").replace("{","（").replace("}","）").replace("\n"," ")
    chunks=textwrap.wrap(text,16 if h>w else 30)
    content="\\N".join(chunks)
    path.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,{38 if h>w else 30},&H00FFFFFF,&H00FFFFFF,&H001A1A1A,&H60000000,0,0,0,0,100,100,0,0,1,2,1,2,45,45,{125 if h>w else 70},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:04.90,Default,,0,0,0,,{content}
""",encoding="utf-8")

def normalize_audio(folder):
    command=[str(FFMPEG),"-hide_banner","-i","final.tmp.mp4","-af",
             "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json","-f","null","-"]
    flags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
    measured=subprocess.run(command,cwd=folder,capture_output=True,timeout=120,creationflags=flags)
    if measured.returncode:
        (folder/"processing-error.log").write_bytes(measured.stderr[-16000:])
        raise RuntimeError("人声音量检测未完成。")
    logs=measured.stderr.decode("utf-8",errors="replace")
    matches=re.findall(r"\{[^{}]+\}",logs)
    if not matches: raise RuntimeError("没有收到音量检测结果。")
    stats=json.loads(matches[-1])
    if stats["input_i"] in {"-inf","inf"}: raise RuntimeError("人声轨道为空，不能输出无声成片。")
    af=("loudnorm=I=-16:TP=-1.5:LRA=11:"
        f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
        f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
        f"offset={stats['target_offset']}:linear=true")
    run([FFMPEG,"-hide_banner","-loglevel","error","-y","-i","final.tmp.mp4","-t","15","-c:v","copy",
         "-af",af,"-ar","48000","-c:a","aac","-b:a","128k","-movflags","+faststart","final.normalized.mp4"],folder)
    os.replace(folder/"final.normalized.mp4",folder/"final.tmp.mp4")
    (folder/"loudness.json").write_text(json.dumps({"before":stats,"target_lufs":-16,"target_true_peak_db":-1.5},indent=2),encoding="utf-8")

def build_video(job,config,progress):
    folder=JOBS/job["id"]; folder.mkdir(exist_ok=True)
    payload=job["payload"]; plan=payload["plan"]
    (folder/"storyboard.json").write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding="utf-8")
    w,h=(720,1280) if plan["ratio"]=="9:16" else (1280,720)
    reference=UPLOADS/(payload["reference_id"]+".jpg") if payload.get("reference_id") else None
    if reference and not reference.exists(): raise RuntimeError("参考图已删除，请重新上传。")
    if job["mode"]=="preview":
        for i,shot in enumerate(plan["shots"],1):
            make_card(plan,shot,folder/f"scene{i}.jpg",reference)
        with Image.open(folder/"scene1.jpg") as cover:
            cover.save(folder/"cover.jpg",quality=92)
    else:
        run([FFMPEG,"-loglevel","error","-y","-ss","1","-i","source.mp4","-frames:v","1","cover.jpg"],folder)
    for i in range(1,4):
        path=folder/f"voice{i}.wav"
        if path.exists():
            try:
                good=path.stat().st_size>100 and duration(path)>0.1
            except Exception:
                good=False
            if not good:
                path.unlink(missing_ok=True)
                path.with_suffix(".json").unlink(missing_ok=True)
    progress("voice","正在生成中文配音（本地 Kokoro）")
    pending=[{"text":shot["narration"],"voice":payload["voice"],"output":str(folder/f"voice{i}.wav")}
             for i,shot in enumerate(plan["shots"],1) if not (folder/f"voice{i}.wav").exists()]
    if pending:
        manifest=folder/"voice-tasks.json"
        manifest.write_text(json.dumps(pending,ensure_ascii=False),encoding="utf-8")
        with TTS_LOCK:
            run([TTS_PYTHON,"-B",ROOT/"app/tts_batch.py","--manifest",manifest,
                 "--root",TTS_ROOT,"--device",config["tts_device"]],folder,timeout=360)
    for i in range(1,4):
        if not (folder/f"voice{i}.wav").exists() or duration(folder/f"voice{i}.wav")<=0.1:
            raise RuntimeError(f"第 {i} 段配音未完成，请继续处理已有任务。")
    progress("voice","三段配音已完成，准备按镜头对齐")
    source=folder/"source.mp4"
    if job["mode"]=="kling":
        if not source.exists(): raise RuntimeError("缺少可灵源视频，任务尚未完成生成。")
        if duration(source)<14.8: raise RuntimeError("可灵源视频不足 15 秒，未通过时长检查。")
    progress("composing","正在对齐镜头、声音与字幕")
    for i,shot in enumerate(plan["shots"],1):
        voice=folder/f"voice{i}.wav"; voice_duration=duration(voice)
        tempo=max(1.0,voice_duration/4.7)
        if tempo>2.5: raise RuntimeError(f"第 {i} 段旁白太长，请缩短旁白后创建新任务。")
        ass=folder/f"captions{i}.ass"; write_subtitle(ass,shot,w,h)
        if job["mode"]=="preview":
            inputs=["-loop","1","-framerate","24","-i",f"scene{i}.jpg","-i",f"voice{i}.wav"]
            vf=f"scale={w}:{h},zoompan=z='min(zoom+0.00012,1.018)':d=1:s={w}x{h}:fps=24,subtitles=captions{i}.ass,format=yuv420p"
        else:
            inputs=["-ss",str((i-1)*5),"-i","source.mp4","-i",f"voice{i}.wav"]
            vf=f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,subtitles=captions{i}.ass,format=yuv420p"
        filters=f"[0:v]{vf}[v];[1:a]atempo={tempo:.5f},aresample=48000,apad,atrim=duration=5,alimiter=limit=0.89[a]"
        run([FFMPEG,"-hide_banner","-loglevel","error","-y",*inputs,"-filter_complex",filters,
             "-map","[v]","-map","[a]","-t","5","-r","24","-c:v","libx264","-preset","fast","-crf","21",
             "-c:a","aac","-b:a","128k","-ac","2","-movflags","+faststart",f"clip{i}.mp4"],folder)
        progress("composing",f"已合成第 {i}/3 个镜头")
    (folder/"concat.txt").write_text("".join(f"file 'clip{i}.mp4'\n" for i in range(1,4)),encoding="utf-8")
    run([FFMPEG,"-hide_banner","-loglevel","error","-y","-f","concat","-safe","0","-i","concat.txt",
         "-c","copy","-movflags","+faststart","final.tmp.mp4"],folder)
    progress("composing","正在统一人声音量")
    normalize_audio(folder)
    progress("verifying","正在检查视频与音频")
    info=probe(folder/"final.tmp.mp4")
    streams=info["streams"]; actual=float(info["format"]["duration"])
    if not 14.9<=actual<=15.2 or not any(x["codec_type"]=="audio" for x in streams):
        raise RuntimeError("成片时长或音频检查未通过。")
    run([FFMPEG,"-v","error","-i","final.tmp.mp4","-f","null","-"],folder)
    os.replace(folder/"final.tmp.mp4",folder/"final.mp4")
    if job["mode"]=="kling":
        run([FFMPEG,"-loglevel","error","-y","-ss","1","-i","final.mp4","-frames:v","1","cover.jpg"],folder)
    srt=""
    for i,shot in enumerate(plan["shots"]):
        srt+=f"{i+1}\n{srt_time(i*5)} --> {srt_time(i*5+4.9)}\n{shot['narration']}\n\n"
    (folder/"subtitles.srt").write_text(srt,encoding="utf-8-sig")
    report={"duration":actual,"mode":job["mode"],"resolution":f"{w}x{h}","fps":24,
            "technical_check":"passed","visual_review":"需由用户预览验收"}
    (folder/"qa.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
