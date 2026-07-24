# SRT Sub Master

一个“服务器保存字幕、本机保存视频和模型”的在线字幕工作台。网站可部署到自己的
Linux 服务器；MP4 只会从浏览器复制到当前电脑的本机识别器，不经过 Linux API。

## 已实现的能力

- 管理员创建账号，Argon2id 密码哈希，HttpOnly + Secure Cookie 登录。
- 一次性配对码绑定网站账号和 Mac/Windows 本机识别器。
- Apple 芯片使用 MLX Whisper，Windows 优先 NVIDIA CUDA，否则 CPU INT8。
- `large-v3`、`large-v3-turbo`、`small` 模型下载、进度和断点续传。
- 自动发现桌面“视频转文字工具”已经下载的 MLX `large-v3`。
- MP4 流式复制、SHA-256、音轨/时长检查、磁盘余量检查和本机永久留存。
- 识别进度同步、字幕滚动校对、当前行高亮、点击跳转、500ms 自动保存。
- TXT/SRT 从服务器中的最新编辑版本实时生成。
- 跨设备重新选择原文件并按哈希、大小和时长验证。
- 删除任务后向离线设备保留待执行的本机副本删除指令；用户原始文件不修改。
- React 深层路由刷新回退、Docker Compose、Caddy 自动 HTTPS。

## 目录

```text
web/        React 19 + TypeScript + Vite
server/     FastAPI + SQLite
agent/      回环地址本机识别器
deploy/     Docker Compose + Caddy
installer/ Mac/Windows 安装包构建脚本
```

关键数据不会放在浏览器存储中。账号、任务和字幕持久化到 Linux 的 SQLite 卷；
视频、模型和本机任务状态持久化到识别器应用数据目录。

## 本地开发（macOS）

需要 Node.js 22、Python 3.11/3.12、pnpm 与 FFmpeg。分别运行：

```bash
./scripts/dev-server.command
./scripts/dev-agent.command
./scripts/dev-web.command
```

浏览器打开 `http://localhost:5173`。本地默认管理员为 `admin / change-me-now`，
仅用于开发。

## Linux 部署

1. 将域名 A/AAAA 记录指向服务器，开放 TCP 80/443 和 UDP 443。
2. 先构建安装包，并把两个文件放进 `installer/artifacts/`。
3. 复制部署配置并填写真实域名、随机密钥和强密码：

```bash
cp deploy/.env.example deploy/.env
cd deploy
docker compose --env-file .env up -d --build
```

Caddy 自动申请证书。数据库位于 Docker 卷 `srt_data`，建议定期备份该卷。
Linux 镜像中不安装 Whisper、FFmpeg、CUDA 或模型，也没有接收视频的 API。

升级前可备份数据库：

```bash
docker compose exec api sh -c 'cp /data/srt-sub.sqlite3 /data/srt-sub.backup.sqlite3'
```

## 构建本机安装包

macOS Apple Silicon：

```bash
chmod +x installer/macos/build.sh
./installer/macos/build.sh
```

Windows x64（PowerShell，需要 FFmpeg 与 Inno Setup 6）：

```powershell
.\installer\windows\build.ps1
```

没有 Apple Developer ID 或 Windows 代码签名证书时，首次打开会出现系统安全提示。
发布给他人前建议配置签名与公证。

## 浏览器与安全边界

- 首版只支持 Chrome/Edge；首次连接 `127.0.0.1` 时需要允许本地网络访问。
- 本机识别器只监听 `127.0.0.1:43921`，并只接受配对网站的 Origin。
- 写操作和视频 Range 流都使用服务器签发、绑定账号/设备/任务的短期令牌。
- 网站必须使用 HTTPS；登录接口、任务接口和字幕接口都有所有权检查。
- 视频不会自动删除。只有用户在历史页明确删除任务时，识别器副本才会删除；
  用户最初选择的 MP4 永远不会被修改。

## 验证

```bash
pnpm install
pnpm build
pnpm test:web
server/.venv/bin/python -m pytest server/tests agent/tests
docker compose -f deploy/compose.yaml config
```

API 文档在部署后的 `/api/docs`，OpenAPI JSON 在 `/api/openapi.json`。
