from pathlib import Path

project_dir = Path(SPECPATH).parent

a = Analysis(
    [str(project_dir / "native_app.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[(str(project_dir / "app" / "static"), "app/static")],
    hiddenimports=["webview.platforms.cocoa", "webview.js"],
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
    name="Clean Reader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
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
    name="Clean Reader",
)
app = BUNDLE(
    coll,
    name="Clean Reader.app",
    icon=None,
    bundle_identifier="local.cleanreader.app",
    version="1.0.0",
    info_plist={
        "CFBundleDisplayName": "Clean Reader",
        "CFBundleName": "Clean Reader",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "13.0",
    },
)
