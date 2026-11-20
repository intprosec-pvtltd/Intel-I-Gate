FROM python:3.11-slim
WORKDIR /srv/backend
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements*.txt ./
RUN pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir -r requirements-ai.txt
COPY backend/ ./
COPY scripts/ /srv/scripts/
RUN useradd --create-home intel && mkdir -p storage/uploads storage/temporary storage/snapshots ai_models && chown -R intel:intel /srv
USER intel
EXPOSE 8000
CMD ["uvicorn","app.main:create_app","--factory","--host","0.0.0.0","--port","8000","--workers","1"]
