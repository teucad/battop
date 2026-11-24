# PyInstaller spec for the Windows build: onefile, windowed. Run via tools/build_windows.ps1.
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

root = Path(SPECPATH)
ns = {}
exec((root / "battop" / "__init__.py").read_text(encoding="utf-8"), ns)
version = ns["__version__"]
nums = tuple((int(p) for p in version.split(".")[:3])) + (0,) * (4 - len(version.split(".")[:3]))

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("FileDescription", "Battop"),
            StringStruct("FileVersion", version),
            StringStruct("InternalName", "Battop"),
            StringStruct("OriginalFilename", "Battop.exe"),
            StringStruct("ProductName", "Battop"),
            StringStruct("ProductVersion", version),
        ])]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

a = Analysis(
    ["battop.pyw"],
    pathex=[str(root)],
    datas=[
        ("battop/locales", "battop/locales"),
        ("battop/assets", "battop/assets"),
    ],
    hiddenimports=["pystray._win32"],
    excludes=["battop.platforms.linux"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="Battop",
    icon="battop/assets/battop.ico",
    version=version_info,
    console=False,
    upx=False,
)
