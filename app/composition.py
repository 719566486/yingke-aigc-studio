"""Compose optional narration, native character dialogue, and optional music."""
import json
import os
from PIL import Image
from . import media as m
from .store import AUDIO_UPLOADS


def caption_cues(shot,audio_mode):
    duration=shot.get("duration",5)
    if audio_mode=="narration":return [(0,duration-.1,shot["narration"])] if shot.get("narration") else []
    if audio_mode!="dialogue":return []
    from .story import speech_seconds
    events=shot.get("events") or shot.get("turns") or ([{"kind":"dialogue","speaker_name":shot.get("speaker",""),"text":shot["dialogue"]}] if shot.get("dialogue") else [])
    actions=sum(e.get("kind")=="action" for e in events)
    action_time=shot.get("action_seconds",0)/actions if actions else 0
    cues=[];cursor=.15
    for event in events:
        if event.get("kind")=="action":cursor+=action_time;continue
        length=max(.5,speech_seconds(event["text"])+.18)
        end=min(duration-.1,cursor+length)
        if end>cursor:cues.append((cursor,end,event.get("speaker_name",event.get("speaker",""))+"："+event["text"]))
        cursor=end+.05
    return cues


def caption(shot,audio_mode):
    return "\n".join(text for _,_,text in caption_cues(shot,audio_mode))


def write_captions(path,shot,mode,w,h):
    cues=caption_cues(shot,mode)
    if not cues:return False
    m.write_subtitle(path,{**shot,"narration":""},w,h)
    header=path.read_text(encoding="utf-8").split("Dialogue:",1)[0]
    def ass_time(value):
        n=round(value*100);return f"{n//360000}:{n//6000%60:02}:{n//100%60:02}.{n%100:02}"
    lines=[]
    for start,end,text in cues:
        text=text.replace("\\","＼").replace("{","（").replace("}","）").replace("\n"," ")
        import textwrap
        content="\\N".join(textwrap.wrap(text,16 if h>w else 30))
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{content}\n")
    path.write_text(header+"".join(lines),encoding="utf-8")
    return True


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
    native=job["mode"]=="kling" and ((mode=="dialogue" and any(s.get("turns") or s.get("dialogue") for s in plan["shots"])) or bgm=="ai")
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
    offset=0
    for i,shot in enumerate(plan["shots"],1):
        seconds=shot.get("duration",5)
        has_captions=write_captions(folder/f"captions{i}.ass",shot,mode,w,h)
        if job["mode"]=="preview":
            inputs=["-loop","1","-framerate","24","-i",f"scene{i}.jpg"]
            vf=f"scale={w}:{h},zoompan=z='min(zoom+0.00012,1.018)':d=1:s={w}x{h}:fps=24"
        else:
            inputs=["-ss",str(offset),"-i","source.mp4"]
            vf=f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
        if has_captions:vf+=f",subtitles=captions{i}.ass"
        filters=f"[0:v]{vf},format=yuv420p[v]"
        audio_map=[]
        if speech:
            if shot.get("narration"):
                voice=folder/f"voice{i}.wav";voice_seconds=m.duration(voice);tempo=max(1.0,voice_seconds/max(.4,seconds-.3))
                if tempo>2.5:raise RuntimeError(f"第{i}段旁白太长，请缩短后创建新任务。")
                inputs+=["-i",str(voice)]
            else:
                tempo=1.0;inputs+=["-f","lavfi","-i","anullsrc=r=48000:cl=stereo"]
            filters+=f";[1:a]atempo={tempo:.5f},aresample=48000,apad,atrim=duration={seconds}[voc]"
            if native:
                filters+=";[0:a]aresample=48000,volume=0.4[bed];[voc][bed]amix=inputs=2:duration=first:normalize=0[a]"
            else:filters+=";[voc]anull[a]"
            audio_map=["-map","[a]"]
        elif native:
            filters+=f";[0:a]aresample=48000,apad,atrim=duration={seconds}[a]"
            audio_map=["-map","[a]"]
        m.run([m.FFMPEG,"-hide_banner","-loglevel","error","-y",*inputs,"-filter_complex",filters,"-map","[v]",*audio_map,
               "-t",str(seconds),"-r","24","-c:v","libx264","-preset","fast","-crf","21",
               *(["-c:a","aac","-b:a","128k","-ac","2"] if audio_map else ["-an"]),"-movflags","+faststart",f"clip{i}.mp4"],folder)
        progress("composing",f"已合成第{i}/{len(plan['shots'])}个镜头")
        offset+=seconds
    (folder/"concat.txt").write_text("".join(f"file 'clip{i}.mp4'\n" for i in range(1,len(plan["shots"])+1)),encoding="utf-8")
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
    srt="";number=0;offset=0
    for shot in plan["shots"]:
        for start,end,text in caption_cues(shot,mode):
            number+=1;srt+=f"{number}\n{m.srt_time(offset+start)} --> {m.srt_time(offset+end)}\n{text}\n\n"
        offset+=shot.get("duration",5)
    (folder/"subtitles.srt").write_text(srt,encoding="utf-8-sig")
    (folder/"qa.json").write_text(json.dumps({"duration":seconds,"mode":job["mode"],"audio_mode":mode,"bgm_mode":bgm,"has_audio":audio_expected,
        "native_dialogue":native and mode=="dialogue","dialogue_timing":"按剧情时长估算显示台词，非语音识别或逐字强制对齐",
        "resolution":f"{w}x{h}","fps":24,"technical_check":"passed","visual_review":"需预览验收口型、台词和配乐效果"},ensure_ascii=False,indent=2),encoding="utf-8")
