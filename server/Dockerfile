FROM node:22-alpine AS web-builder
WORKDIR /build
RUN corepack enable
COPY package.json pnpm-workspace.yaml ./
COPY web/package.json web/package.json
RUN pnpm install --no-frozen-lockfile
COPY web web
RUN pnpm --dir web build

FROM alpine:3.22 AS geo-db
WORKDIR /geo
RUN wget -q -O ip2region_v4.xdb \
      https://raw.githubusercontent.com/lionsoul2014/ip2region/cd40e3a1d532d645697999d646cf0e10481cef33/data/ip2region_v4.xdb && \
    echo "6307a9696f5711f84bcb8b25f07894de68a64a0ed4a1cc7e990562dd3084f210  ip2region_v4.xdb" \
      | sha256sum -c - && \
    wget -q -O ip2region_v6.xdb \
      https://raw.githubusercontent.com/lionsoul2014/ip2region/cd40e3a1d532d645697999d646cf0e10481cef33/data/ip2region_v6.xdb && \
    echo "5b93da35ac28bc316dccc54a758381f7a874ae0461dd51ff5df5e34815586f11  ip2region_v6.xdb" \
      | sha256sum -c -

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    SRT_WEB_DIST=/app/web/dist \
    SRT_IP2REGION_V4_PATH=/app/server/data/ip2region_v4.xdb \
    SRT_IP2REGION_V6_PATH=/app/server/data/ip2region_v6.xdb \
    FORWARDED_ALLOW_IPS=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fd00::/8
WORKDIR /app
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt
COPY server /app/server
COPY --from=geo-db /geo /app/server/data
COPY douyin_engine /app/douyin_engine
COPY THIRD_PARTY_NOTICES.md /app/THIRD_PARTY_NOTICES.md
COPY --from=web-builder /build/web/dist /app/web/dist
RUN useradd --create-home --uid 10001 srt && \
    mkdir -p /data && \
    chown -R srt:srt /data /app
USER srt
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
