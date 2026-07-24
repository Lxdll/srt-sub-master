FROM node:22-alpine AS web-builder
WORKDIR /build
RUN corepack enable
COPY package.json pnpm-workspace.yaml ./
COPY web/package.json web/package.json
RUN pnpm install --no-frozen-lockfile
COPY web web
RUN pnpm --dir web build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SRT_WEB_DIST=/app/web/dist \
    SRT_DOWNLOADS_DIR=/app/installer/artifacts
WORKDIR /app
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt
COPY server /app/server
COPY --from=web-builder /build/web/dist /app/web/dist
COPY installer/artifacts /app/installer/artifacts
RUN useradd --create-home --uid 10001 srt && \
    mkdir -p /data /app/installer/artifacts && \
    chown -R srt:srt /data /app
USER srt
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
