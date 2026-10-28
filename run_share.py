import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for key in ("TEMP", "TMP"):
    os.environ[key] = str(ROOT / "work")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
if __name__ == "__main__":
    (ROOT / "work/share-gateway.pid").write_text(str(os.getpid()), encoding="ascii")
    import uvicorn
    uvicorn.run("app.share:app", host="127.0.0.1", port=8788, access_log=False)
