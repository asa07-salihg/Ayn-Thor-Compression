"""Every external tool the app can fetch: where from, and what it must hash to.

Why
    This app downloads executables from the internet and runs them. Before this
    manifest existed it fetched whatever a URL returned and wrote it straight
    into `tools/`, which means a hijacked release asset, a compromised mirror
    or a captive-portal HTML page would all have been installed without a
    complaint. Every file therefore carries a SHA-256 taken from the exact
    pinned release, and `manager` refuses to install a file that does not match.

    Two consequences worth knowing about:

    * Versions are pinned. Upgrading a tool is a deliberate edit here, with a
      new checksum, not something that happens silently on a user's machine.
    * One entry has no checksum. Dolphin publishes its Windows builds only from
      its own server, with no signature or published digest, so there is
      nothing to pin against. `manager` installs it with a warning, and the
      Tools dialog offers to copy DolphinTool.exe out of an existing Dolphin
      install instead. See THIRD-PARTY-NOTICES.md.

Used by
    `core.tools.manager.ToolsManager`, `ui.tools_dialog`.

Reference
    Each entry's `homepage` is the upstream project. Checksums were taken from
    the pinned artifacts; THIRD-PARTY-NOTICES.md records how to re-derive them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolFile:
    """One file that ends up in `tools/`."""

    name: str
    # Path inside the archive, matched against the end of each entry's path.
    # None means the download *is* the file.
    member: str | None = None
    # None means upstream offers nothing stable to pin against; see the module
    # docstring. Anything else is a lowercase hex SHA-256 of the final file.
    sha256: str | None = None
    optional: bool = False


@dataclass(frozen=True)
class ToolSpec:
    key: str
    label: str
    description: str
    homepage: str
    license: str
    version: str
    files: tuple[ToolFile, ...]
    url: str | None = None
    pip_package: str | None = None
    # zip and 7z archives are unpacked; exe means the download is the tool.
    archive: str = "exe"
    # 7z archives need the 7zr bootstrap, which is fetched first.
    needs_7zr: bool = False
    manual_hint: str = ""
    formats: tuple[str, ...] = field(default_factory=tuple)

    def filenames(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.files if not f.optional)


# The bootstrap. 7zr is a standalone extractor with no dependencies, which is
# the only way to unpack the .7z archives the other tools ship in.
BOOTSTRAP_KEY = "7zr"


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        key=BOOTSTRAP_KEY,
        label="7zr (bootstrap)",
        description="Standalone extractor used to unpack the other tools' .7z archives.",
        homepage="https://www.7-zip.org/",
        license="LGPL-2.1-or-later",
        version="26.02",
        url="https://github.com/ip7z/7zip/releases/download/26.02/7zr.exe",
        archive="exe",
        files=(
            ToolFile("7zr.exe",
                     sha256="56b8cc9f4971cef253644fafe54063ed7fdca551d4dee0f8c6baa81b855acd72"),
        ),
    ),
    ToolSpec(
        key="chdman",
        label="chdman (MAME)",
        description="CHD for PS1, PS2, PSP and Dreamcast disc images.",
        homepage="https://www.mamedev.org/",
        license="GPL-2.0-or-later",
        version="namDHC v2.0 build",
        url="https://github.com/umageddon/namDHC/releases/download/v2.0/chdman.exe",
        archive="exe",
        files=(
            ToolFile("chdman.exe",
                     sha256="e475e5422e17557f38ec8e430e001cf566f377fed353d43c33a9fd8ce70c729d"),
        ),
        manual_hint="Or install MAME from mamedev.org and copy chdman.exe into tools/.",
        formats=("CHD",),
    ),
    ToolSpec(
        key="DolphinTool",
        label="DolphinTool",
        description="RVZ for GameCube and Wii disc images.",
        homepage="https://dolphin-emu.org/",
        license="GPL-2.0-or-later",
        version="2506a",
        url="https://dl.dolphin-emu.org/releases/2506a/dolphin-2506a-x64.7z",
        archive="7z",
        needs_7zr=True,
        # Dolphin publishes no checksums for these builds and hosts them
        # outside any signed distribution channel, so there is nothing to pin.
        files=(ToolFile("DolphinTool.exe", member="DolphinTool.exe", sha256=None),),
        manual_hint=(
            "Dolphin builds are unsigned and unpublished as checksums. If you already "
            "have Dolphin installed, use 'Select DolphinTool...' to copy the exe you "
            "already trust instead of downloading a second one."
        ),
        formats=("RVZ",),
    ),
    ToolSpec(
        key="maxcso",
        label="maxcso",
        description="CSO, ZSO and DAX for PSP and PS2 ISO images.",
        homepage="https://github.com/unknownbrackets/maxcso",
        license="ISC",
        version="1.13.0",
        url="https://github.com/unknownbrackets/maxcso/releases/download/v1.13.0/maxcso_v1.13.0_windows.7z",
        archive="7z",
        needs_7zr=True,
        files=(
            ToolFile("maxcso.exe", member="maxcso.exe",
                     sha256="05f90b74c4ccdb48f93f9e4c51cc96eb959fd7596d79ba80cf6d8008495fadfb"),
        ),
        formats=("CSO",),
    ),
    ToolSpec(
        key="7z",
        label="7-Zip",
        description="7z and ZIP archives for cartridge ROMs and arcade romsets.",
        homepage="https://www.7-zip.org/",
        license="LGPL-2.1-or-later",
        version="26.02",
        url="https://github.com/ip7z/7zip/releases/download/26.02/7z2602-extra.7z",
        archive="7z",
        needs_7zr=True,
        # The extras archive ships x86 at the root with x64/ and arm64/ beside
        # it. The member paths are explicit because picking "the first 7za.exe
        # found" installed the 32-bit build on 64-bit machines.
        files=(
            ToolFile("7za.exe", member="x64/7za.exe",
                     sha256="35d4d69d7cd6cb44558f208c3b1334268013f9daf82d2dda848893a1c30c59c2"),
            ToolFile("7za.dll", member="x64/7za.dll",
                     sha256="8105eab695801f9c9fcc234c7963a7ac217378916821618dfb9d97b04562b82e"),
        ),
        formats=("7z", "ZIP"),
    ),
    ToolSpec(
        key="ndstrim",
        label="ndstrim",
        description="Trims the unused tail off Nintendo DS cart images.",
        homepage="https://github.com/Nemris/ndstrim",
        license="MIT",
        version="0.2.1",
        url="https://github.com/Nemris/ndstrim/releases/download/v0.2.1/ndstrim_v0.2.1_x86_64-pc-windows-gnu.zip",
        archive="zip",
        files=(
            ToolFile("ndstrim.exe", member="ndstrim.exe",
                     sha256="873aa31f43b8b90378c871b2797c9e9cd1f3c38a996b8edf6e226d0862c71add"),
        ),
        formats=("NDS trim",),
    ),
    ToolSpec(
        key="rom-converto",
        label="rom-converto",
        description="WUA for Wii U, and the preferred ZCCI engine for 3DS.",
        homepage="https://github.com/DevYukine/rom-converto",
        license="MIT",
        version="0.20.0",
        url=("https://github.com/DevYukine/rom-converto/releases/download/v0.20.0/"
             "rom-converto-cli-windows-x64.exe"),
        archive="exe",
        files=(
            ToolFile("rom-converto.exe",
                     sha256="c29228bfc9d38ec0342ea319172a548989314e703bcabec4ca2c94fcf481ae32"),
        ),
        formats=("WUA", "ZCCI"),
    ),
    ToolSpec(
        key="3ds-decryptor",
        label="3DS Decryptor",
        description="ctrtool, decrypt and makerom: removes 3DS cart and CIA encryption.",
        homepage="https://github.com/xxmichibxx/Batch-CIA-3DS-Decryptor-Redux",
        license="MIT",
        version="1.0.6.3",
        # Pinned to a tag, not to refs/heads/main: a branch archive changes
        # whenever the branch moves, so its contents could never be verified.
        url=("https://github.com/xxmichibxx/Batch-CIA-3DS-Decryptor-Redux/archive/"
             "refs/tags/v1.0.6.3.zip"),
        archive="zip",
        files=(
            ToolFile("ctrtool.exe", member="bin/ctrtool.exe",
                     sha256="921ab18aa2e0ca4ed1e7537f7dc1803a6eaae7c7251a678d6704111c7cb912e5"),
            ToolFile("decrypt.exe", member="bin/decrypt.exe",
                     sha256="35506bc9c5610cd41c7a6e6c377b01bca30217e61d5b5e4842156120fa9e59a0"),
            ToolFile("makerom.exe", member="bin/makerom.exe",
                     sha256="db810fb9c3d41ecaefa8fcbd13140ecafe9b95e6303cd9244c12a2bca70fa938"),
            ToolFile("seeddb.bin", member="bin/seeddb.bin",
                     sha256="ccdcea5e4465194158737462436ec10ae48669dd961902282ac2861e260d03c9"),
        ),
        formats=("Decrypt 3DS",),
    ),
    ToolSpec(
        key="z3ds_compress",
        label="z3ds_compress",
        description="Reference Azahar ZCCI compressor. Optional fallback for rom-converto.",
        homepage="https://github.com/energeticokay/z3ds_compress",
        license="GPL-3.0-or-later",
        version="corruption_fix",
        url=("https://github.com/energeticokay/z3ds_compress/releases/download/"
             "corruption_fix/z3ds_compressor_windows.zip"),
        archive="zip",
        files=(
            ToolFile("z3ds_compressor.exe", member="z3ds_compressor.exe",
                     sha256="d83f6f557896ef74bd491b9a6443d99db7b2ba7754e465a5c0d5d52369da6576"),
            ToolFile("libstdc++-6.dll", member="libstdc++-6.dll",
                     sha256="428d22a8a4d25e39edad36851122701b3460c2bcf628884cdd2664530d2dd634"),
            ToolFile("libwinpthread-1.dll", member="libwinpthread-1.dll",
                     sha256="f0c48bcf1f1f0a65b4f99406f56db7349ded8866cd86548687ab6a98e859af35"),
            ToolFile("libzstd.dll", member="libzstd.dll",
                     sha256="b13d4f30b93c96823473d742dda0075f7334cba03a40c33d8a7dc282e37b1500"),
            ToolFile("libgcc_s_seh-1.dll", member="libgcc_s_seh-1.dll",
                     sha256="2de4355648441db0230a9aba1a149fc829b094f83c14c37ea3f775356d33d8b1"),
        ),
        formats=("ZCCI",),
    ),
    ToolSpec(
        key="nsz",
        label="nsz",
        description="NSZ and XCZ for Nintendo Switch titles. Installed as a Python package.",
        homepage="https://github.com/nicoboss/nsz",
        license="MIT",
        version=">=5.0.0",
        pip_package="nsz",
        # A pip install is verified by pip against PyPI, so there is nothing
        # for this manifest to hash.
        files=(),
        formats=("NSZ",),
    ),
)

SPECS_BY_KEY = {spec.key: spec for spec in TOOL_SPECS}

# Every tool except the bootstrap, which is an implementation detail.
INSTALLABLE = tuple(spec for spec in TOOL_SPECS if spec.key != BOOTSTRAP_KEY)
