"""Fetch the same Chinese Kokoro weights during image build, never on visitor requests."""
from pathlib import Path
import os
from huggingface_hub import snapshot_download

root = Path(os.environ.get("STUDIO_TTS_ROOT", "/opt/tts"))
snapshot_download(
    "hexgrad/Kokoro-82M-v1.1-zh",
    revision="4f4ed9d286bcdaea692b6d514eaf14dd8af9602f",
    local_dir=root / "models/kokoro-v1.1-zh",
    allow_patterns=["config.json", "kokoro-v1_1-zh.pth", "voices/zf_001.pt", "voices/zf_003.pt", "voices/zm_010.pt", "voices/zm_009.pt", "README.md", "LICENSE*"],
)
print("Chinese model and four voices ready")
