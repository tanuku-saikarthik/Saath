# One container: the family app (built) served by the FastAPI backend.
#   docker build -t saath .
#   docker run -p 8000:8000 --env-file .env -v saath-data:/data saath
# Add the voice model with: docker build --build-arg VOICE=1 -t saath .

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ARG VOICE=0
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt backend/requirements-voice.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && if [ "$VOICE" = "1" ]; then pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-voice.txt; fi
COPY backend/ ./
COPY --from=web /web/dist /app/web/dist

# The database and recordings live on a volume so they survive redeploys.
ENV DATABASE_URL=sqlite:////data/saath.db DATA_DIR=/data
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
