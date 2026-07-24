$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path "$PSScriptRoot\..\..").Path
$ArtifactDir = Join-Path $ProjectDir "installer\artifacts"
$BuildDir = Join-Path $ProjectDir "build\windows"
$VenvDir = Join-Path $BuildDir "venv"

if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    throw "Windows 安装包需要在 x64 构建机上生成。"
}

New-Item -ItemType Directory -Force $ArtifactDir | Out-Null
New-Item -ItemType Directory -Force (Join-Path $ProjectDir "agent\bin") | Out-Null

$Ffprobe = (Get-Command ffprobe.exe -ErrorAction SilentlyContinue).Source
$Ffmpeg = (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue).Source
if (-not $Ffprobe -or -not $Ffmpeg) {
    throw "未找到 ffmpeg.exe/ffprobe.exe，请先安装 FFmpeg 并加入 PATH。"
}
Copy-Item $Ffprobe (Join-Path $ProjectDir "agent\bin\ffprobe.exe") -Force
Copy-Item $Ffmpeg (Join-Path $ProjectDir "agent\bin\ffmpeg.exe") -Force

python -m venv $VenvDir
& "$VenvDir\Scripts\pip.exe" install --upgrade pip pyinstaller
& "$VenvDir\Scripts\pip.exe" install -r "$ProjectDir\agent\requirements-windows.txt"
Push-Location $ProjectDir
try {
    & "$VenvDir\Scripts\pyinstaller.exe" --clean --noconfirm agent\srt_sub_agent.spec
} finally {
    Pop-Location
}

$Iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $Iscc) {
    throw "未找到 Inno Setup 6（ISCC.exe）。"
}
& $Iscc "/DProjectDir=$ProjectDir" "/DArtifactDir=$ArtifactDir" `
    "$ProjectDir\installer\windows\installer.iss"
