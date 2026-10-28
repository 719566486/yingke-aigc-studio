import os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
(ROOT/"work").mkdir(exist_ok=True)
for key in ("TEMP","TMP"): os.environ[key]=str(ROOT/"work")
os.environ["PYTHONIOENCODING"]="utf-8"
os.environ["PYTHONDONTWRITEBYTECODE"]="1"
if __name__=="__main__":
    import uvicorn
    uvicorn.run("app.main:app",host="127.0.0.1",port=8787,access_log=False)
