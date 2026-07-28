# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH).parent.parent
agent_bin = project_root / "agent" / "bin"
datas = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "multipart",
]
if agent_bin.exists():
    datas.append((str(agent_bin), "agent/bin"))
engine = "mlx_whisper" if sys.platform == "darwin" else "faster_whisper"
engine_datas, engine_binaries, engine_hidden = collect_all(engine)
datas += engine_datas
hiddenimports += engine_hidden

a = Analysis(
    [str(project_root / "agent" / "launcher.py")],
    pathex=[str(project_root)],
    binaries=engine_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SRTSubAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="不二 本机识别器.app",
        bundle_identifier="com.srtsub.agent",
        info_plist={
            "CFBundleName": "不二 本机识别器",
            "NSHighResolutionCapable": True,
            "LSUIElement": True,
        },
    )
