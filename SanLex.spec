# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('licenses', 'licenses'), ('THIRD_PARTY_NOTICES.md', '.'), ('README.md', '.'), ('LICENSE', '.'), ('sanlex', 'source/sanlex'), ('scripts', 'source/scripts'), ('requirements.txt', 'source'), ('requirements-dev.txt', 'source'), ('run.py', 'source'), ('assets', 'source/assets'), ('licenses', 'source/licenses'), ('tests', 'source/tests'), ('THIRD_PARTY_NOTICES.md', 'source'), ('README.md', 'source'), ('LICENSE', 'source'), ('C:\\workspace\\ThreeKingdoms\\build\\bundled-data', 'bundled-data')],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='SanLex',
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
    icon=['C:\\workspace\\ThreeKingdoms\\assets\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SanLex',
)
