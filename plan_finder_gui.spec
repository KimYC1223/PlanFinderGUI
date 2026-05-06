# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

block_cipher = None

if sys.platform == 'darwin':
    app_icon = 'img/scv.icns'
elif sys.platform == 'win32':
    app_icon = 'img/scv.ico'
else:
    app_icon = None

a = Analysis(
    ['app.py'],
    pathex=[str(Path('src').resolve())],
    binaries=[],
    datas=[
        ('img', 'img'),
        ('sound', 'sound'),
        ('src/plan_finder_gui/presets', 'presets'),
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtMultimedia',
        'qasync',
        'markdown',
        'psutil',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == 'darwin':
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='PlanFinder',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        icon='img/scv.icns',
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='PlanFinder',
    )
    app = BUNDLE(
        coll,
        name='PlanFinder.app',
        icon='img/scv.icns',
        bundle_identifier='com.planfinder.gui',
        info_plist={
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '11.0',
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='PlanFinder',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        icon='img/scv.icns',
    )
