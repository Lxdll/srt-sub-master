#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/../.." && pwd)"
artifact_dir="$project_dir/installer/artifacts"
build_dir="$project_dir/build/macos"
venv_dir="$build_dir/venv"
python_cmd="python3"
if command -v python3.12 >/dev/null 2>&1; then
  python_cmd="python3.12"
elif command -v python3.11 >/dev/null 2>&1; then
  python_cmd="python3.11"
fi

mkdir -p "$artifact_dir" "$project_dir/agent/bin"
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "Mac 安装包只能在 Apple Silicon 构建机上生成。"
  exit 1
fi
ffprobe_source="$(command -v ffprobe || true)"
ffmpeg_source="$(command -v ffmpeg || true)"
if [[ -z "$ffprobe_source" || -z "$ffmpeg_source" ]]; then
  echo "未找到 ffmpeg/ffprobe，请先安装 FFmpeg。"
  exit 1
fi
cp "$ffprobe_source" "$project_dir/agent/bin/ffprobe"
cp "$ffmpeg_source" "$project_dir/agent/bin/ffmpeg"

"$python_cmd" -m venv "$venv_dir"
"$venv_dir/bin/pip" install --upgrade pip pyinstaller
"$venv_dir/bin/pip" install -r "$project_dir/agent/requirements-macos.txt"
(
  cd "$project_dir"
  "$venv_dir/bin/pyinstaller" --clean --noconfirm agent/srt_sub_agent.spec
)

stage="$build_dir/dmg"
rm -rf "$stage"
mkdir -p "$stage"
mv "$project_dir/dist/不二 本机识别器.app" "$stage/不二 本机识别器.app"
ln -s /Applications "$stage/Applications"
hdiutil create -volname "不二 本机识别器" \
  -srcfolder "$stage" -ov -format UDZO \
  "$artifact_dir/srt-sub-agent-macos-arm64.dmg"
echo "已生成 $artifact_dir/srt-sub-agent-macos-arm64.dmg"
