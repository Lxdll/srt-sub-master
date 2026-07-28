FROM debian:bookworm-slim AS whisper-builder
ARG WHISPER_CPP_VERSION=v1.8.3
ARG WHISPER_MODEL_SHA256=ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb
ARG WHISPER_VAD_SHA256=2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential ca-certificates cmake curl && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN curl -fsSL --retry 3 \
      "https://github.com/ggml-org/whisper.cpp/archive/refs/tags/${WHISPER_CPP_VERSION}.tar.gz" \
      -o whisper.tar.gz && \
    mkdir source && \
    tar -xzf whisper.tar.gz --strip-components=1 -C source && \
    cmake -S source -B source/build \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_C_FLAGS_RELEASE="-O2 -DNDEBUG" \
      -DCMAKE_CXX_FLAGS_RELEASE="-O2 -DNDEBUG" \
      -DBUILD_SHARED_LIBS=OFF \
      -DGGML_NATIVE=OFF \
      -DGGML_AVX=ON \
      -DGGML_AVX2=ON \
      -DGGML_FMA=ON \
      -DGGML_F16C=ON \
      -DGGML_AVX512=OFF \
      -DGGML_AVX512_VBMI=OFF \
      -DGGML_AVX512_VNNI=OFF \
      -DWHISPER_BUILD_TESTS=OFF \
      -DWHISPER_BUILD_EXAMPLES=ON && \
    cmake --build source/build --config Release --target whisper-cli -j1
RUN mkdir -p /opt/whisper/bin /opt/whisper/models && \
    cp source/build/bin/whisper-cli /opt/whisper/bin/whisper-cli && \
    curl -fsSL --retry 3 \
      "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin" \
      -o /opt/whisper/models/ggml-small-q5_1.bin && \
    echo "${WHISPER_MODEL_SHA256}  /opt/whisper/models/ggml-small-q5_1.bin" \
      | sha256sum -c - && \
    curl -fsSL --retry 3 \
      "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v6.2.0.bin" \
      -o /opt/whisper/models/ggml-silero-v6.2.0.bin && \
    echo "${WHISPER_VAD_SHA256}  /opt/whisper/models/ggml-silero-v6.2.0.bin" \
      | sha256sum -c -

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=9000
WORKDIR /app
COPY --from=whisper-builder /opt/whisper /opt/whisper
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*
COPY fc_worker/requirements.txt /app/fc_worker/requirements.txt
RUN pip install --no-cache-dir -r /app/fc_worker/requirements.txt
COPY fc_worker /app/fc_worker
COPY server /app/server
COPY douyin_engine /app/douyin_engine
EXPOSE 9000
CMD ["python", "-m", "uvicorn", "fc_worker.app:app", "--host", "0.0.0.0", "--port", "9000", "--timeout-keep-alive", "3600"]
