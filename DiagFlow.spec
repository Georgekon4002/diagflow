# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('C:\\Users\\georg\\Desktop\\internship\\diagflow\\frontend', 'frontend')]
binaries = []
hiddenimports = ['uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'anyio', 'anyio._backends._asyncio', 'diagflow.main', 'diagflow.api.routes', 'diagflow.api.schemas', 'diagflow.api.dependencies', 'diagflow.services.assignment', 'diagflow.services.diagnostician', 'diagflow.services.pamakristos', 'diagflow.services.slis_sync', 'diagflow.db.diagflow_db', 'diagflow.db.engines', 'diagflow.db.models', 'diagflow.db.slis_models', 'diagflow.engine.pipeline', 'diagflow.engine.filters', 'diagflow.engine.scoring', 'diagflow.engine.rules', 'diagflow.engine.solver', 'diagflow.config', 'diagflow.utils.logging', 'structlog', 'pydantic_settings', 'apscheduler', 'apscheduler.schedulers.asyncio', 'webview', 'webview.platforms.winforms', 'webview.platforms.edgechromium', 'webview.platforms.win32', 'webview.platforms.mshtml', 'pyodbc', 'sqlalchemy.dialects.mssql', 'clr', 'pythonnet', 'clr_loader', 'ortools', 'ortools.sat.python.cp_model']
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pythonnet')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('clr_loader')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ortools')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:\\Users\\georg\\Desktop\\internship\\diagflow\\src\\diagflow\\launcher.py'],
    pathex=['C:\\Users\\georg\\Desktop\\internship\\diagflow\\src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'scipy', 'skimage', 'easyocr', 'cv2', 'pandas', 'numpy', 'pytest', 'sympy', 'matplotlib', 'PIL', 'openpyxl'],
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
    icon=['C:\\Users\\georg\\Desktop\\internship\\diagflow\\media\\logos\\logo.ico'],
)
