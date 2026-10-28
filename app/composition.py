"""Compose optional narration, native character dialogue, and optional music."""
import json
import os
from PIL import Image
from . import media as m
from .store import AUDIO_UPLOADS


def caption(shot, audio_mode):
    if audio_mode=="narration": return shot.get("narration","")
    if audio_mode=="dialogue" and shot.get("dialogue"):
        return shot.get("speaker","")+"："+shot["dialogue"]
    return ""


def has_audio(path):
    return any(s["codec_type"]=="audio" for s in m.probe(path)["streams"])


def mix_upload(folder, music, volume, foreground):
    music_filter=f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=duration=15,asetpts=PTS-STARTPTS,volume={volume:.4f},afade=t=in:d=0.6,afade=t=out:st=14:d=1[bg]"
    if foreground:
        filters=music_filter+";[0:a]asplit=2[voice][control];[bg][control]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=250[duck];[voice][duck]amix=inputs=2:duration=first:normalize=0[a]"
    else:
        filters=music_filter+";[bg]anull[a]"
    m.run([m.FFMPEG,"-hide_banner","-loglevel","error","-y","-i","final.tmp.mp4","-stream_loop","-1","-i",music,
           "-filter_complex",filters,"-map","0:v:0","-map","[a]","-t","15","-c:v","copy","-c:a","aac","-b:a","128k","-ac","2",
           "-movflags","+faststart","music-mix.mp4"],folder)
    os.replace(folder/"music-mix.mp4",folder/"final.tmp.mp4")


def build_video(job,config,progress):
    folder=m.JOBS/job["id"];folder.mkdir(exist_ok=True)
    payload=job["payload"];plan=payload["plan"];mode=plan.get("audio_mode","narration")
    bgm=payload.get("bgm_mode",plan.get("bgm_mode","none"))
    native=job["mode"]=="kling" and (mode=="dialogue" or bgm=="ai")
    speech=mode=="narration" and any(s.get("narration") for s in plan["shots"])
    w,h=(720,1280) if plan["ratio"]=="9:16" else (1280,720)
    (folder/"storyboard.json").write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding="utf-8")
    reference=m.UPLOADS/(payload["reference_id"]+".jpg") if payload.get("reference_id") else None
    if reference and not reference.is_file(): raise RuntimeError("参考图已删除，请重新上传。")
    if job["mode"]=="preview":
        for i,shot in enumerate(plan["shots"],1):m.make_card(plan,shot,folder/f"scene{i}.jpg",reference)
        with Image.open(folder/"scene1.jpg") as image:image.save(folder/"cover.jpg",quality=92)
    else:
        if not (folder/"source.mp4").is_file() or m.duration(folder/"source.mp4")<14.8:
            raise RuntimeError("缺少足够15秒的可灵源视频。")
        if native and not has_audio(folder/"source.mp4"):
            raise RuntimeError("可灵源视频没有音轨，未生成请求的对白或AI配乐；不会用旁白替代人物说话。")
    if speech:
        progress("voice","正在生成已填写的旁白，空白镜头不加旁白")
        pending=[]
        for i,shot in enumerate(plan["shots"],1):
            if not shot.get("narration"):continue
            path=folder/f"voice{i}.wav"
            if path.exists():
                try:valid=path.stat().st_size>100 and m.duration(path)>.1
                except Exception:valid=False
                if not valid:path.unlink()
            if not path.exists():pending.append({"text":shot["narration"],"voice":payload["voice"],"output":str(path)})
        if pending:
            manifest=folder/"voice-tasks.json";manifest.write_text(json.dumps(pending,ensure_ascii=False),encoding="utf-8")
            with m.TTS_LOCK:
                m.run([m.TTS_PYTHON,"-B",m.ROOT/"app/tts_batch.py","--manifest",manifest,"--root",m.TTS_ROOT,"--device",config["tts_device"]],folder,timeout=360)
    else:
        progress("voice","保留人物原声与口型" if native and mode=="dialogue" else "按选择制作，不添加旁白")
    progress("composing","正在合成画面与所选声音")
    for i,shot in enumerate(plan["shots"],1):
        text=caption(shot,mode)
        if text:m.write_subtitle(folder/f"captions{i}.ass",{**shot,"narration":text},w,h)
        if job["mode"]=="preview":
            inputs=["-loop","1","-framerate","24","-i",f"scene{i}.jpg"]
            vf=f"scale={w}:{h},zoompan=z='min(zoom+0.00012,1.018)':d=1:s={w}x{h}:fps=24"
        else:
            inputs=["-ss",str((i-1)*5),"-i","source.mp4"]
            vf=f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
        if text:vf+=f",subtitles=captions{i}.ass"
        filters=f"[0:v]{vf},format=yuv420p[v]"
        audio_map=[]
        if speech:
            if shot.get("narration"):
                voice=folder/f"voice{i}.wav";seconds=m.duration(voice);tempo=max(1.0,seconds/4.7)
                if tempo>2.5:raise RuntimeError(f"第{i}段旁白太长，请缩短后创建新任务。")
                inputs+=["-i",str(voice)]
            else:
                tempo=1.0;inputs+=["-f","lavfi","-i","anullsrc=r=48000:cl=stereo"]
            filters+=f";[1:a]atempo={tempo:.5f},aresample=48000,apad,atrim=duration=5[voc]"
            if native:
                filters+=";[0:a]aresample=48000,volume=0.4[bed];[voc][bed]amix=inputs=2:duration=first:normalize=0[a]"
            else:filters+=";[voc]anull[a]"
            audio_map=["-map","[a]"]
        elif native:
            filters+=";[0:a]aresample=48000,apad,atrim=duration=5[a]"
            audio_map=["-map","[a]"]
        m.run([m.FFMPEG,"-hide_banner","-loglevel","error","-y",*inputs,"-filter_complex",filters,"-map","[v]",*audio_map,
               "-t","5","-r","24","-c:v","libx264","-preset","fast","-crf","21",
               *(["-c:a","aac","-b:a","128k","-ac","2"] if audio_map else ["-an"]),"-movflags","+faststart",f"clip{i}.mp4"],folder)
        progress("composing",f"已合成第{i}/3个镜头")
    (folder/"concat.txt").write_text("".join(f"file 'clip{i}.mp4'\n" for i in range(1,4)),encoding="utf-8")
    m.run([m.FFMPEG,"-hide_banner","-loglevel","error","-y","-f","concat","-safe","0","-i","concat.txt","-c","copy","-movflags","+faststart","final.tmp.mp4"],folder)
    if bgm=="upload":
        music=AUDIO_UPLOADS/(payload["bgm_id"]+".mp3")
        if not music.is_file():raise RuntimeError("背景音乐已删除，请重新上传。")
        progress("composing","正在加入背景音乐，自动降低对白期间的音乐音量")
        mix_upload(folder,music,payload.get("bgm_volume",.2),speech or native)
    audio_expected=speech or native or bgm=="upload"
    if audio_expected:m.normalize_audio(folder)
    progress("verifying","正在检查成片")
    info=m.probe(folder/"final.tmp.mp4");seconds=float(info["format"]["duration"])
    if not 14.9<=seconds<=15.2 or (audio_expected and not has_audio(folder/"final.tmp.mp4")):
        raise RuntimeError("成片时长或音轨检查未通过。")
    m.run([m.FFMPEG,"-v","error","-i","final.tmp.mp4","-f","null","-"],folder)
    os.replace(folder/"final.tmp.mp4",folder/"final.mp4")
    if job["mode"]=="kling":m.run([m.FFMPEG,"-loglevel","error","-y","-ss","1","-i","final.mp4","-frames:v","1","cover.jpg"],folder)
    srt="";number=0
    for i,shot in enumerate(plan["shots"]):
        text=caption(shot,mode)
        if not text:continue
        number+=1;srt+=f"{number}\n{m.srt_time(i*5)} --> {m.srt_time(i*5+4.9)}\n{text}\n\n"
    (folder/"subtitles.srt").write_text(srt,encoding="utf-8-sig")
    (folder/"qa.json").write_text(json.dumps({"duration":seconds,"mode":job["mode"],"audio_mode":mode,"bgm_mode":bgm,"has_audio":audio_expected,
        "native_dialogue":native and mode=="dialogue","dialogue_timing":"按镜头显示台词，非逐字强制对齐",
        "resolution":f"{w}x{h}","fps":24,"technical_check":"passed","visual_review":"需预览验收口型、台词和配乐效果"},ensure_ascii=False,indent=2),encoding="utf-8")
