# Third-party notices

This application is a front end. It bundles or downloads the programs below,
each of which remains under its own licence and copyright. Nothing here is
modified; the app invokes each tool on the command line.

## Converter tools

| Project | Version | Licence | Used for | Verified |
|---|---|---|---|:---:|
| [chdman](https://www.mamedev.org/) (MAME) | namDHC v2.0 build | GPL-2.0-or-later | CHD | yes |
| [DolphinTool](https://dolphin-emu.org/) | 2506a | GPL-2.0-or-later | RVZ | **no** |
| [maxcso](https://github.com/unknownbrackets/maxcso) | 1.13.0 | ISC | CSO, ZSO, DAX | yes |
| [7-Zip](https://www.7-zip.org/) | 26.02 | LGPL-2.1-or-later (with unRAR restriction) | 7z, ZIP | yes |
| [ndstrim](https://github.com/Nemris/ndstrim) | 0.2.1 | MIT | NDS trim | yes |
| [rom-converto](https://github.com/DevYukine/rom-converto) | 0.20.0 | MIT | WUA, ZCCI | yes |
| [z3ds_compress](https://github.com/energeticokay/z3ds_compress) | `corruption_fix` | GPL-3.0-or-later | ZCCI (fallback engine) | yes |
| [nsz](https://github.com/nicoboss/nsz) | >= 5.0.0 | MIT | NSZ, XCZ | pip |
| [Batch CIA 3DS Decryptor Redux](https://github.com/xxmichibxx/Batch-CIA-3DS-Decryptor-Redux) | 1.0.6.3 | MIT | Decrypt 3DS | yes |
| [Project_CTR](https://github.com/3DSGuy/Project_CTR) (ctrtool, makerom) | in the above | MIT | Decrypt 3DS | yes |

The authoritative list is
[`core/tools/manifest.py`](src/aynthor/core/tools/manifest.py), which pins each
version and records a SHA-256 for every extracted file.

`seeddb.bin` is compiled by the 3DS homebrew community; it is redistributed
with the Batch CIA 3DS Decryptor Redux repository.

The GPL-licensed tools are invoked as separate processes and are not linked
into this application.

## How the downloads are verified

Every file is downloaded to a scratch directory, unpacked there, hashed, and
copied into `tools/` only once its SHA-256 matches the manifest. A mismatch is
reported and nothing is installed. Three details matter more than they look:

- **Versions are pinned.** Upgrading a tool means editing the manifest and
  recording a new hash by hand, so an upstream release that moves cannot change
  what lands on a user's machine.
- **Archive members are matched by their full path inside the archive.** The
  7-Zip extras archive ships x86 at the root with `x64/` and `arm64/` beside it,
  all three containing a file called `7za.exe`; matching on filename alone
  installed the 32-bit build on 64-bit machines. Only the named members are
  extracted, so an archive cannot drop extra files beside the binaries the app
  runs.
- **Nothing is pinned to a branch.** The 3DS decryptor URL ends
  `/archive/refs/tags/v1.0.6.3.zip`, not `/refs/heads/main.zip`: a branch
  archive changes whenever the branch moves, so its contents can never be
  verified.

To check a hash yourself, download the URL from the manifest and run
`Get-FileHash <file> -Algorithm SHA256`. For an archive the recorded hash is of
the **extracted** file, so unpack it first and hash the member the manifest
names.

**DolphinTool is the one entry that cannot be verified.** Dolphin publishes its
Windows builds from `dl.dolphin-emu.org` with no signature and no digest, so the
manifest records `sha256=None`, the Tools window marks the row **unverified**,
and **Use my DolphinTool...** copies the exe from a Dolphin install you already
trust instead. It is the only such entry, and `tests/test_tools.py` fails if
another appears.

**Tools > Check for updates** asks each project whether its pinned version is
still the latest and stops there: a build that is not in the manifest has no
checksum to be verified against, so an updated tool ships in the next release of
this app. `python scripts/check_tool_updates.py` is the same check from a
terminal. A check makes one unauthenticated request per tool and GitHub allows
sixty an hour from one address; past that it answers 403, which is reported as
rate limiting and clears by itself. DolphinTool is the one it cannot check, so
look at <https://dolphin-emu.org/download/> when cutting a release.

nsz is a Python package rather than an exe: pip installs it, pip's own
verification against PyPI applies, and there is nothing for the manifest to
hash. It must be 5.0.0 or newer, because 4.x calls `sys.exit(1)` at import time
when no keys file is present, which fails the frozen build on any machine
without `prod.keys`.

## Python dependencies

| Package | Licence |
|---|---|
| [PySide6](https://www.qt.io/qt-for-python) | LGPL-3.0 |
| [nsz](https://github.com/nicoboss/nsz) | MIT |
| [zstandard](https://github.com/indygreg/python-zstandard) | BSD-3-Clause |

PySide6 is used under the LGPL. It is bundled unmodified in the released
executable, and the application does not link statically against Qt.

## Reference material

Folder layout follows
[ES-DE-Directories](https://github.com/retrogamecorps/ES-DE-Directories).

Format documentation used while writing the parsers:
[3dbrew](https://www.3dbrew.org/) (NCCH and NCSD headers),
[switchbrew](https://switchbrew.org/) (NCA layout and title ids),
[GBATEK](https://problemkaputt.de/gbatek.htm) (DS cart header), and the
[zstd seekable format specification](https://github.com/facebook/zstd/blob/dev/contrib/seekable_format/zstd_seekable_compression_format.md).

## What is not distributed

No ROMs, no console keys, no BIOS images, and no copyrighted game data. This
project does not provide any, does not download any, and does not link to any.
