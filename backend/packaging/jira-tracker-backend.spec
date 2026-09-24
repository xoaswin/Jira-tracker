# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata

datas = [('C:/Users/AswinAnanthakumar/OneDrive - zeb/Desktop/ezjira/jira-tracker/backend/alembic.ini', 'backend'), ('C:/Users/AswinAnanthakumar/OneDrive - zeb/Desktop/ezjira/jira-tracker/backend/alembic', 'backend/alembic'), ('C:/Users/AswinAnanthakumar/OneDrive - zeb/Desktop/ezjira/jira-tracker/frontend/dist', 'frontend/dist')]
binaries = []
hiddenimports = ['keyring.backends.Windows']
datas += copy_metadata('keyring')
tmp_ret = collect_all('win32ctypes')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:/Users/AswinAnanthakumar/OneDrive - zeb/Desktop/ezjira/jira-tracker/backend/app/main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'sentence_transformers', 'pytest', 'respx', 'pytest_asyncio'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='jira-tracker-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='jira-tracker-backend',
)
