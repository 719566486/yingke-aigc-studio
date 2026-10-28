"""Synthesize all three narration segments with a single offline model load."""
import argparse, json, os, time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--manifest",required=True);p.add_argument("--root",required=True);p.add_argument("--device",choices=["cpu","cuda"],default="cuda")
args=p.parse_args();root=Path(args.root).resolve()
for key,sub in {"TEMP":"work","TMP":"work","HF_HOME":"cache/huggingface","TORCH_HOME":"cache/torch","NUMBA_CACHE_DIR":"cache/numba","MPLCONFIGDIR":"cache/matplotlib","XDG_CACHE_HOME":"cache"}.items():
    os.environ[key]=str(root/sub)
os.environ.update(HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",HF_HUB_DISABLE_TELEMETRY="1",GRADIO_ANALYTICS_ENABLED="False")
import numpy as np, soundfile as sf, torch
from kokoro import KModel, KPipeline
start=time.perf_counter();torch.set_num_threads(4);torch.manual_seed(42)
directory=root/"models/kokoro-v1.1-zh"
model=KModel(repo_id="hexgrad/Kokoro-82M-v1.1-zh",config=str(directory/"config.json"),model=str(directory/"kokoro-v1_1-zh.pth")).to(args.device).eval()
en=KPipeline(lang_code="a",repo_id="hexgrad/Kokoro-82M-v1.1-zh",model=False)
def english(value): return next(en(value)).phonemes
pipeline=KPipeline(lang_code="z",repo_id="hexgrad/Kokoro-82M-v1.1-zh",model=model,en_callable=english)
tasks=json.loads(Path(args.manifest).read_text(encoding="utf-8"))
output_root=Path(__file__).resolve().parent.parent/"data/jobs"
for task in tasks:
    out=Path(task["output"]).resolve()
    if not out.is_relative_to(output_root.resolve()): raise RuntimeError("Output is outside the studio.")
    voice=directory/"voices"/(task["voice"]+".pt")
    if not voice.is_file(): raise RuntimeError("Unknown voice")
    if out.exists(): continue
    chunks=[r.audio.numpy() for r in pipeline(task["text"],voice=str(voice),speed=1.08) if r.audio is not None]
    if not chunks: raise RuntimeError("No audio generated")
    samples=np.concatenate(chunks)
    if not np.isfinite(samples).all() or np.max(np.abs(samples))<1e-5: raise RuntimeError("Invalid audio")
    sf.write(str(out),samples,24000,subtype="PCM_16")
    out.with_suffix(".json").write_text(json.dumps({"engine":"kokoro-batch","seconds":len(samples)/24000,"device":args.device,"voice":task["voice"],"elapsed_seconds":time.perf_counter()-start},ensure_ascii=False,indent=2),encoding="utf-8")
    print("VOICE_READY",out.name,flush=True)
