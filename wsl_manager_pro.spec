# -*- mode: python ; coding: utf-8 -*-

block_cipher = None


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/icon.ico', 'assets'),
        ('assets/icon.png', 'assets'),
        ('distros.json', '.'),
        ('resources/i18n/en.json', 'resources/i18n'),
        ('resources/i18n/es.json', 'resources/i18n'),
        ('resources/i18n/pt.json', 'resources/i18n'),
        ('resources/styles/dark.qss', 'resources/styles'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='WSLManagerPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon='assets/icon.ico',
)
