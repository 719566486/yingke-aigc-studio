from __future__ import annotations
import json, math, os, random, re, subprocess, threading, textwrap, wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
from .store import ROOT, JOBS, UPLOADS
FFMPEG = Path(os.environ.get("STUDIO_FFMPEG", r"D:\workspace\tools\ffmpeg\ffmpeg-8.1.2-essentials_build\bin\ffmpeg.exe" if os.name == "nt" else "/usr/bin/ffmpeg"))
FFPROBE = Path(os.environ.get("STUDIO_FFPROBE", str(FFMPEG.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))))
TTS_ROOT = Path(os.environ.get("STUDIO_TTS_ROOT", r"D:\workspace\local_tts"))
TTS_PYTHON = Path(os.environ.get("STUDIO_TTS_PYTHON", str(TTS_ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python"))))
TTS_LOCK = threading.Lock()
FONT = Path(os.environ.get("STUDIO_FONT", r"C:\Windows\Fonts\msyh.ttc" if os.name == "nt" else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"))
BOLD = Path(os.environ.get("STUDIO_FONT_BOLD", r"C:\Windows\Fonts\msyhbd.ttc" if os.name == "nt" else "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"))
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
Style: Default,{os.environ.get('STUDIO_CAPTION_FONT', 'Microsoft YaHei' if os.name == 'nt' else 'Noto Sans CJK SC')},{38 if h>w else 30},&H00FFFFFF,&H00FFFFFF,&H001A1A1A,&H60000000,0,0,0,0,100,100,0,0,1,2,1,2,45,45,{125 if h>w else 70},1

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
    if stats["input_i"] in {"-inf","inf"}: raise RuntimeError("音轨为空，未得到所选的声音。")
    af=("loudnorm=I=-16:TP=-1.5:LRA=11:"
        f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
        f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
        f"offset={stats['target_offset']}:linear=true")
    run([FFMPEG,"-hide_banner","-loglevel","error","-y","-i","final.tmp.mp4","-t","15","-c:v","copy",
         "-af",af,"-ar","48000","-c:a","aac","-b:a","128k","-movflags","+faststart","final.normalized.mp4"],folder)
    os.replace(folder/"final.normalized.mp4",folder/"final.tmp.mp4")
    (folder/"loudness.json").write_text(json.dumps({"before":stats,"target_lufs":-16,"target_true_peak_db":-1.5},indent=2),encoding="utf-8")

def build_video(job,config,progress):
    from .composition import build_video as compose
    return compose(job,config,progress)
