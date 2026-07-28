# 不二

一个以字幕校对为核心的在线工作台，并提供独立的单条抖音视频解析与下载页。字幕流程中，视频、音频、模型和语音识别都在用户自己的电脑上完成；网站只接收 SRT 字幕，用于逐句修改、保存和导出。

## 架构

```text
任意 AI / 用户
    │ 调用本地命令
    ▼
universal-skill/local-video-to-srt
    │ 本机读取视频、本机运行 Whisper
    ▼
SRT 文件
    │ 用户主动上传
    ▼
网站校对、保存、导出 TXT/SRT
```

通用本地工具不绑定 Codex、豆包、DeepSeek 或其他特定 AI。它提供稳定的命令行和 JSON 输入输出协议；任何能够执行本地命令的 AI 客户端都可以接入。不能执行本地命令的聊天客户端仍需要用户手动运行工具。

## 通用本地转写工具

目录：`universal-skill/local-video-to-srt/`

本机需要：

- Python 3.11 或 3.12
- FFmpeg（同时需要 `ffmpeg` 和 `ffprobe`）
- macOS Apple Silicon：`mlx-whisper`
- Windows：`faster-whisper`

macOS 安装依赖：

```bash
cd universal-skill/local-video-to-srt
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-macos.txt
```

检查环境：

```bash
.venv/bin/python scripts/local_video_to_srt.py doctor --json
```

查看模型：

```bash
.venv/bin/python scripts/local_video_to_srt.py models --json
```

生成字幕：

```bash
.venv/bin/python scripts/local_video_to_srt.py transcribe "/绝对路径/video.mp4" \
  --output "/绝对路径/video.srt" \
  --model large-v3-turbo \
  --language zh \
  --json
```

默认情况下，转写引擎可能从模型原始仓库下载所选模型。已有模型时使用 `--model-path "/绝对路径/model"`，可以完全复用本地文件。

`SKILL.md` 是给 AI 阅读的通用工作流，`skill.json` 是平台无关的命令协议。不同 AI 平台可以在它们自己的工具调用层上做薄适配，但共享同一套本地转写代码。

## 网站能力

- 独立管理后台创建访问账号，Argon2id 密码哈希，HttpOnly Cookie 登录。
- 导入 UTF-8 编码的 SRT，单文件最大 5MB。
- 可选本机视频播放；浏览器使用临时对象地址，视频不会上传网站。
- 字幕逐句校对、时间轴跳转、500ms 自动保存。
- 从最新编辑版本导出 TXT 或 SRT。
- 使用兼容 OpenAI 接口的模型检测社交媒体违禁词，并结合每个账号的个人词库。
- 使用同一模型服务拆解视频脚本，输出制作内容清单、亮点、钩子和优化建议。
- 用户之间的任务和字幕严格隔离。

## 违禁词检测

拥有“违禁词检测”权限的账号可访问 `/prohibited-words`。用户粘贴文案后，服务端调用兼容 OpenAI Chat Completions 的模型查找原文中可定位的风险词句，再与当前账号的个人词库合并、去重并标注命中位置。检测原文和结果不写入数据库，个人词库按账号隔离保存。

配置模型服务：

```dotenv
SRT_MODERATION_API_BASE=https://api.example.com/v1
SRT_MODERATION_API_KEY=replace-with-api-key
SRT_MODERATION_MODEL=replace-with-model-name
SRT_MODERATION_TIMEOUT_SECONDS=30
SRT_SCRIPT_ANALYSIS_TIMEOUT_SECONDS=150
```

`SRT_MODERATION_API_BASE` 应指向提供 `/chat/completions` 的 API 根路径。未完整配置时检测接口会明确返回“模型尚未配置”，不会把调用失败当作无风险。检测文字会发送到所配置的第三方模型服务，请根据该服务的隐私政策和数据处理条款使用。

## 脚本拆解

拥有“脚本拆解”权限的账号可访问 `/script-analysis`。用户可以直接输入脚本，
也可以选择不超过 10MB 的 `.docx` 文档；Word 正文在浏览器本地读取，原文件
不会上传。提交分析后，服务端复用上方的兼容 OpenAI 模型配置，返回内容概览、
逐段制作拆解、所需内容清单、脚本亮点、钩子和整体优化建议。

脚本和分析结果不写入数据库。为了防止模型虚构原文，逐段拆解、亮点和钩子的
原文摘录会在服务端再次校验，不存在于原脚本中的项目不会返回。脚本文字会发送
到所配置的第三方模型服务，请根据该服务的隐私政策和数据处理条款使用。
脚本拆解默认允许模型响应 150 秒，与更轻量的违禁词检测超时分别配置。

## 抖音视频下载

登录后访问 `/douyin`。该页面与字幕任务完全解耦，不创建字幕任务、不写视频数据库，也不会在服务器保存下载历史或完整视频文件。

- 解析线路自动选择：优先使用已配对的本机组件，本机不可用时自动切换云端。
- 自动使用最高/推荐画质，解析结果支持在线播放。
- 支持保存到指定目录或由浏览器直接下载，并显示成功、失败和取消状态。
- 解析结果缓存 15 分钟，下载票据 10 分钟失效；下载通过响应流直接传给浏览器。
- 首版仅支持单个视频，不支持图集、主页批量、直播或音频提取。

生产环境默认仅管理员可用。相关配置：

```dotenv
SRT_DOUYIN_ENABLED=true
SRT_DOUYIN_ACCESS=authenticated
SRT_DOUYIN_COOKIE_FILE=/run/secrets/douyin-cookie.txt
# 不方便挂载文件时才使用：
SRT_DOUYIN_COOKIE=
SRT_BHWA_API_BASE=https://downloader-api.bhwa233.com
```

推荐将管理员维护的抖音 Cookie 以只读文件挂载到 API 容器，并让 `SRT_DOUYIN_COOKIE_FILE` 指向容器内路径。服务会根据文件修改时间自动热加载；Cookie 不写入数据库、接口响应或日志。抖音下载是否可用由管理后台的“抖音下载”权限点控制。

该功能通过限速、缓存、熔断和故障切换降低触发平台风控的概率，不使用 IP 轮换、账号池、验证码破解或 Cloudflare Worker 伪装，也不承诺绕过平台限制。请仅下载本人拥有或已获得授权的内容。

## 抖音链接转文案

同时拥有“抖音下载”和“字幕校对”权限的账号可访问
`/douyin-transcribe`。粘贴单条抖音分享链接后，网站会创建字幕任务并直接进入
校对页。生产环境可把任务异步提交到阿里云函数计算 FC：FC 将视频流式写入
私有 OSS、提取音频，并使用 Whisper Small Q5_1 多语言模型生成带时间轴的
字幕；网站服务器只保留 API、SQLite 和字幕编辑能力。

- 只做原声语言转写，不把外语翻译为中文。
- 单条最长 30 分钟、最大 500MB；每个账号最多排队 3 条。
- FC 最大实例数和单实例并发均设为 1，一次只识别一条，避免意外消耗 CU。
- 原视频在私有 OSS 保留 7 天用于同步播放，字幕保留到用户删除任务。
- 临时视频总配额为 10GB；过期清理后仍超限时拒绝新任务。

模型和 `whisper.cpp` 已固定版本并在 FC 镜像构建时校验哈希。相关配置：

```dotenv
SRT_TRANSCRIPTION_ENABLED=true
SRT_TRANSCRIPTION_BACKEND=fc
SRT_TRANSCRIPTION_THREADS=2
SRT_TRANSCRIPTION_MAX_DURATION_SECONDS=1800
SRT_TRANSCRIPTION_MAX_SOURCE_BYTES=524288000
SRT_TRANSCRIPTION_MEDIA_RETENTION_HOURS=168
SRT_TRANSCRIPTION_MEDIA_QUOTA_BYTES=10737418240
```

FC 镜像、RAM 最小权限、OSS 生命周期、额度告警和本地 Worker 回退步骤见
[`fc_worker/README.md`](fc_worker/README.md)。

## 本地开发

需要 Node.js 22、Python 3.11/3.12 与 pnpm。分别运行：

```bash
./scripts/dev-server.command
./scripts/dev-web.command
```

浏览器打开 `http://localhost:5173`。本地默认管理员为 `admin / change-me-now`，仅用于开发。

## Linux 部署

1. 将主域名和后台子域名指向服务器，开放 TCP 80/443 和 UDP 443。
2. 复制部署配置并填写域名、现有代理网络、随机密钥和强密码：

```bash
cp deploy/.env.example deploy/.env
cd deploy
docker compose --env-file .env up -d --build
```

应用容器不占用宿主机端口，通过现有 Caddy 网络提供服务。将
`deploy/Caddyfile` 中的两个站点块合并到现有 Caddy 配置后，由 Caddy
自动申请证书。数据库位于 Docker 卷 `srt_data`，建议定期备份：

```bash
docker compose exec app sh -c 'cp /data/srt-sub.sqlite3 /data/srt-sub.backup.sqlite3'
```

### GitHub 自动部署

`main` 分支的前后端检查全部通过后，GitHub Actions 会构建带提交 SHA
的应用镜像并推送至 GHCR，然后通过 SSH 更新生产容器。部署脚本会等待
容器健康检查；新版本启动失败时自动恢复上一个镜像和 Compose 配置。

仓库需要配置以下 Actions Secrets：

- `PROD_HOST`：生产服务器地址。
- `PROD_USER`：SSH 部署用户。
- `PROD_SSH_KEY`：专用部署私钥，不要使用个人日常 SSH 私钥。
- `PROD_KNOWN_HOSTS`：预先核验过的服务器 SSH Host Key。

服务器运行配置保存在 `/opt/chenjianru/runtime.env`，不会上传到 GitHub。
每次部署使用 `deploy/remote-deploy.sh` 串行更新，备份存放在
`/opt/chenjianru/backups`。

## 隐私边界

- 字幕流程没有视频上传接口。
- 选择用于校对的视频时，文件仅在当前浏览器页面本地播放。
- 通用转写工具只读取用户明确指定的本地文件。
- 模型下载由本地工具在用户发起转写时完成，不经过网站。
- 抖音下载接口只流式转发当前请求的视频内容，不在服务器落盘，也不保存下载历史。
- 违禁词检测原文不保存，但会发送至部署方配置的第三方模型服务；个人词库仅当前账号可见。

## 验证

```bash
pnpm install
pnpm build
pnpm test:web
server/.venv/bin/python -m pytest server/tests agent/tests
docker compose -f deploy/compose.yaml config
```

API 文档在部署后的 `/api/docs`，OpenAPI JSON 在 `/api/openapi.json`。
