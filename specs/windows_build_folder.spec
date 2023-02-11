# -*- mode: python ; coding: utf-8 -*-


block_cipher = None


a = Analysis(
    ['..\\db_reservation_check\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('..\\assets', 'assets'), ('..\\data', 'data'), ('..\\font', 'font'), ('..\\theme', 'theme')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['_gtkagg', '_tkagg', 'bsddb', 'curses', 'pywin.debugger', 'pywin.debugger.dbgcon', 'pywin.dialogs', 'tcl', 'Tkconstants', 'Tkinter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DeutscheBahnReservierungssuche",
    icon='..\\assets\\app_icon.ico',
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

excluded_binaries = [
        'PySide6\\Qt6WebEngineCore.dll',
        'PySide6\\opengl32sw.dll',
        'PySide6\\QtOpenGL.pyd',
        'PySide6\\Qt6Quick.dll',
        'PySide6\\Qt6Designer.dll',
        'PySide6\\Qt6Qml.dll',
        'PySide6\\Qt6Network.dll'
        ]
a.binaries = TOC([x for x in a.binaries if x[0] not in excluded_binaries])

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DeutscheBahnReservierungssuche',
)
