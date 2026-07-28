# 阿里云 FC 转写 Worker

这个目录包含独立的 Function Compute 自定义镜像。Linux 网站通过 FC
异步任务调用它；函数把视频流式写入私有 OSS，运行 FFmpeg 和
`whisper.cpp`，再把结果通过签名回调写回网站的 SQLite。

## 1. 确定名称并创建前置资源

先确定一个**准备创建的函数名称**，例如
`srt-sub-transcription`。此时函数不需要已经存在；后面的 `s deploy`
会按照这个名称自动创建函数。

然后准备以下资源：

1. 确认准备使用的 FC、ACR 和 OSS 位于同一地域。OSS Bucket 必须保持私有。
2. 创建 ACR 镜像仓库，用于保存 FC 自定义容器镜像。
3. 为 FC 创建 RAM 角色，并按
   `ram-policy-worker.json` 中的模板授予指定 Bucket 前缀权限。
4. 在 OSS 中配置生命周期：
   - `douyin-transcriptions/media/`：7 天后删除。
   - `douyin-transcriptions/results/`：建议 1 天后删除。Linux 会在完成
     回调中立即把字幕写入 SQLite。
   - 未完成的分片上传：1 天后自动中止，清理函数超时留下的分片。

此阶段只需要使用 `ram-policy-worker.json`。将其中的 `<BUCKET>`
替换为真实 Bucket 名称，不要给 Bucket 开启公共读。

## 2. 构建镜像并创建函数

在仓库根目录设置以下环境变量。`SRT_FC_FUNCTION_NAME` 填写的是你在
第 1 步确定的名称，不是一个必须预先存在的函数：

```dotenv
SRT_OSS_REGION=cn-hangzhou
SRT_OSS_INTERNAL_ENDPOINT=https://oss-cn-hangzhou-internal.aliyuncs.com
SRT_OSS_BUCKET=your-private-bucket
SRT_FC_FUNCTION_NAME=srt-sub-transcription
SRT_FC_ENDPOINT=<ACCOUNT_ID>.cn-hangzhou.fc.aliyuncs.com
SRT_FC_ROLE_ARN=acs:ram::<ACCOUNT_ID>:role/<ROLE_NAME>
SRT_FC_IMAGE_PUSH=registry.cn-hangzhou.aliyuncs.com/<NAMESPACE>/<REPOSITORY>:<TAG>
SRT_FC_IMAGE=registry-vpc.cn-hangzhou.aliyuncs.com/<NAMESPACE>/<REPOSITORY>:<TAG>
SRT_FC_CALLBACK_URL=https://subtitles.example.com/api/internal/fc/transcription-events
SRT_FC_CALLBACK_SECRET=<至少32位随机字符串>
ALIBABA_CLOUD_ACCESS_KEY_ID=<具有部署和配置函数权限的RAM用户>
ALIBABA_CLOUD_ACCESS_KEY_SECRET=<密钥>
```

`SRT_FC_IMAGE_PUSH` 是本地电脑向 ACR 推送镜像使用的公网地址；
`SRT_FC_IMAGE` 是 FC 拉取同一个镜像使用的 VPC 地址。两者的地域、
命名空间、仓库和标签必须完全一致，只是域名不同。请优先从 ACR
仓库的“基本信息/操作指南”页面复制实际地址。

Apple Silicon 构建时必须生成 AMD64 镜像：

```bash
docker build --platform linux/amd64 \
  -f fc_worker/Dockerfile \
  -t "$SRT_FC_IMAGE_PUSH" .
docker push "$SRT_FC_IMAGE_PUSH"
cd fc_worker
s deploy -y
cd ..
server/.venv/bin/python fc_worker/configure.py
```

其中 `s deploy -y` 会创建名为 `SRT_FC_FUNCTION_NAME` 的 CPU
自定义容器函数；不需要先在 FC 控制台手动创建函数。如果该名称的函数
已经存在，则会更新该函数配置。

`configure.py` 会开启异步任务模式、把最大重试次数设为 0、消息寿命设为
24 小时、预留并发设为 1，并把最小实例数设为 0。部署后仍应在 FC 控制台
复核以下设置：

- 开启异步任务模式。
- 最大实例数设为 1，最小实例数设为 0。
- 异步调用最大重试次数设为 0。
- 保留 `4 vCPU / 4096MB / 512MB / 3600秒 / 单实例并发1`。

## 3. 创建 Linux 调用权限

函数创建成功后，为 Linux 使用的 RAM 用户应用
`ram-policy-linux-invoker.json`。将策略中的 `<BUCKET>`、`<REGION>`、
`<ACCOUNT_ID>` 和 `<FUNCTION_NAME>` 替换为真实值，其中
`<FUNCTION_NAME>` 就是刚刚创建的函数名称。

## 4. Linux 配置

把 `deploy/.env.example` 中的 FC/OSS 变量填入实际部署环境，并确保：

```dotenv
SRT_TRANSCRIPTION_BACKEND=fc
SRT_FC_CALLBACK_SECRET=<与函数完全相同>
SRT_OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
ALIBABA_CLOUD_ACCESS_KEY_ID=<最小权限RAM用户>
ALIBABA_CLOUD_ACCESS_KEY_SECRET=<密钥>
```

正常启动不再包含 Linux 转写容器：

```bash
docker compose -f deploy/compose.yaml up -d --build
```

需要回退本地 Worker 时设置 `SRT_TRANSCRIPTION_BACKEND=local`，然后：

```bash
docker compose -f deploy/compose.yaml \
  --profile local-transcription up -d --build
```

## 5. 额度和运行告警

在阿里云“费用与成本 → 资源包 → 余量预警”中为 15 万 CU 试用包设置
剩余 20% 告警，并启用短信、邮件和站内信；试用包耗尽后会自动转按量，
阿里云不提供扣费硬上限。

同时在 FC/云监控配置：

- 函数错误或超时次数 `>= 1`。
- 异步任务积压 `> 3` 且持续 5 分钟。
- 单任务执行时间超过 40 分钟。
- 函数计算实际账单超过 1 元。

上线前先处理 5、15、30 分钟真实素材。目标是 30 分钟视频冷启动情况下
35 分钟内完成，且单条消耗不高于约 7,000 CU。
