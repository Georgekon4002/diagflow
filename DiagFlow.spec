# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\georg\\Desktop\\internship\\diagflow\\src\\diagflow\\launcher.py'],
    pathex=['C:\\Users\\georg\\Desktop\\internship\\diagflow\\src'],
    binaries=[],
    datas=[('C:\\Users\\georg\\Desktop\\internship\\diagflow\\frontend', 'frontend')],
    hiddenimports=['uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'anyio', 'anyio._backends._asyncio', 'diagflow.main', 'diagflow.api.routes', 'diagflow.api.schemas', 'diagflow.api.dependencies', 'diagflow.services.assignment', 'diagflow.services.diagnostician', 'diagflow.services.pamakristos', 'diagflow.services.comment_parser', 'diagflow.engine.pipeline', 'diagflow.engine.filters', 'diagflow.engine.scoring', 'diagflow.engine.rules', 'diagflow.engine.solver', 'diagflow.config', 'diagflow.utils.logging', 'structlog', 'pydantic_settings'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DiagFlow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\Users\\georg\\Desktop\\internship\\diagflow\\media\\logo.ico'],
)
