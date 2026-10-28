FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    STUDIO_DATA_DIR=/app/data STUDIO_TTS_ROOT=/opt/tts STUDIO_TTS_PYTHON=/usr/local/bin/python \
    STUDIO_TTS_DEVICE=cpu STUDIO_FFMPEG=/usr/bin/ffmpeg STUDIO_FFPROBE=/usr/bin/ffprobe \
    HF_HOME=/opt/tts/cache/huggingface TORCH_HOME=/opt/tts/cache/torch \
    XDG_CACHE_HOME=/opt/tts/cache TEMP=/app/work TMP=/app/work PORT=8080
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 libgomp1 espeak-ng fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
COPY deploy/cloud_requirements.txt ./deploy/
RUN python -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install -r requirements.txt -r deploy/cloud_requirements.txt \
    && python -m pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
COPY deploy/download_cloud_models.py ./deploy/
RUN mkdir -p /opt/tts/work /app/data /app/work \
    && python deploy/download_cloud_models.py \
    && useradd --uid 10001 --create-home --home-dir /app/home studio \
    && chown -R studio:studio /app /opt/tts
COPY --chown=studio:studio app ./app
COPY --chown=studio:studio static ./static
COPY --chown=studio:studio run.py ./
COPY --chown=studio:studio deploy/run_cloud.py ./deploy/
USER studio
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s CMD python -c "import httpx,os; r=httpx.get('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/api/share/ping',timeout=3); r.raise_for_status(); assert r.json()['online']"
CMD ["python", "-B", "deploy/run_cloud.py"]
