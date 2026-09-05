# Contributing

## Getting set up

```powershell
git clone https://github.com/asa07-salihg/Ayn-Thor-Compression.git
cd Ayn-Thor-Compression
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python scripts/fetch_tools.py
python -m aynthor
```

Python 3.10 or newer.

## Before opening a pull request

```powershell
pytest
ruff check .
```

Both run in CI on Linux and Windows, on 3.10 and 3.13.

There is no auto-formatter. `ruff check` covers import order, unused code and
the 100-column limit; beyond that, match the file you are editing. Wrapping a
line where it reads best is a judgement an autoformatter cannot make, and the
diffs it produces bury the change.

If your change touches a converter, say in the pull request which format you
tested and against what. "Converted three PS2 ISOs and NetherSX2 still loads
them" is worth more than a green tick.

## The one architectural rule

**Nothing under `src/aynthor/core/` may import Qt.**

That is what lets the whole engine be tested without a display server, and CI
enforces it by running the suite on Linux with PySide6 not installed. If a piece
of logic needs a `QThread` or a `QSettings`, it belongs in `ui/`.

The corollary: if you find yourself importing from `ui` inside `core`, the type
you need probably belongs in `core/models.py`. That module exists because
`ConversionMode` was once declared twice and `QueueItem` lived in a widget file.

## Module headers

Every module starts with the same three things:

```python
"""One line saying what this is.

Why
    What problem it solves, and what goes wrong without it. Not a restatement
    of the code.

Used by
    Which modules call this, by name.

Reference
    The specification, tool documentation or upstream project this is based on,
    with a URL.
"""
```

This is not decoration. Most of this codebase is decisions about other people's
file formats and command-line flags, and a reader cannot tell a deliberate
choice from an accident without being told which it is. If you cannot fill in
**Why**, that is worth noticing before the code is merged.

The same applies to comments in the body: write down the thing that is not
obvious. `# PS2 needs zlib because NetherSX2 cannot read a zstd CHD` earns its
line. `# set the codec` does not.

## Adding a format

Most formats are a wrapper around a command-line tool. In order:

1. **`core/models.py`**: a new `CompressionFormat` member.
2. **`core/formats.py`**: a `FormatInfo` in the catalogue: the extensions it
   claims, and a `reason` explaining why anyone would pick it over the
   alternatives. Order matters: `detect_format` returns the first entry that
   claims an extension.
3. **`core/modes.py`**: what the Mode dropdown should say. Use the
   destination (`-> CHD`), not the verb.
4. **`core/converters/<name>.py`**: a `BaseConverter` subclass. Validate,
   build the command, call `run_tool`, return `(ok, message)`. Put the tool's
   own error text in the message; yours is a guess, its is a fact.
5. **`core/converters/registry.py`**: one import, one line.
6. **`ui/option_panels.py`**: a panel, if it has settings, plus its
   `BINDINGS` map so saved values can be restored without a hand-written
   loader.
7. **`core/tools/manifest.py`**: the tool, pinned to a version, with a SHA-256
   for every file. See below.
8. **`tests/`**: at minimum, output naming in `test_formats.py`.

The Settings dialog and the queue's context menu are built from the catalogue,
so adding a format puts it in both without touching either.

## Adding or updating a tool

The manifest is the security boundary of this project. A tool that is not
verified is a tool an attacker can replace.

Get the checksum from the extracted file, not the archive:

```bash
# direct download
curl -L -o tool.exe <url>
sha256sum tool.exe

# archive: unpack first, then hash the member the manifest names
unzip -o archive.zip
sha256sum ndstrim.exe
```

Pin to a release tag or a commit. Never to `refs/heads/main`: a branch archive
changes whenever the branch moves, so its contents can never be verified.

Give each `ToolFile` the member's full path inside the archive, not just its
name. The 7-Zip extras archive contains three files called `7za.exe`, one per
architecture, and matching loosely installed the 32-bit build on 64-bit
machines.

`sha256=None` is allowed only when upstream publishes nothing to pin against,
and `tests/test_tools.py` will fail until that test is updated with the reason.
Today there is exactly one such entry, DolphinTool, explained in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Tests

The suite runs without Qt, without a display, and without any converter tool
installed. Keep it that way: build the bytes you need rather than shipping
fixture ROMs.

`tests/conftest.py` has helpers for synthesising NCCH and NCSD headers, and
`tests/test_z3ds.py` builds valid Z3DS containers from the format description.
Those are the pattern to follow for a new binary format.

Test the decision, not the implementation. `test_ps2_preset_avoids_zstd` says
what the app must do and why; a test that asserts a dictionary equals another
dictionary says nothing when it fails.

## Reporting a bug

The Log pane at the bottom of the window is the useful part. The converter's own
error text is usually the line that explains it.

Do not attach ROMs, keys or game data. Filenames and sizes are enough.

## Releasing

New entries go under `## Unreleased` in the changelog, never under the version
number at the top of `__init__.py`. That number is the last thing released, so
writing an entry under it files the change against a build it is not in; three
releases in a row had to be unpicked afterwards before this rule existed.
Cutting a version renames the heading and bumps the two version fields in the
same commit.

A tag triggers the build. The release needs both `AynThorCompression.exe` and
`SHA256SUMS.txt`, from the same build and under exactly those names, or the
updater will refuse it. The version lives in `src/aynthor/__init__.py` and
`pyproject.toml` and the two must agree, because the updater compares the
release tag against the built-in one.

## Security

Anything involving downloads, checksums, network access or key handling: see
[SECURITY.md](SECURITY.md) first, and report privately rather than opening an
issue.

Three rules that are not obvious from reading a diff:

- **All network access goes through `core/net.py`.** It enforces HTTPS through
  redirects, verifies certificates, caps the size and times out. A second HTTP
  client in this codebase is a second set of rules to get right.
- **Nothing reaches `tools/` without matching a checksum in the manifest.** Not
  even a newer version of a tool already there; that is what makes the install
  path meaningful.
- **Nothing runs an executable the user did not ask for.** No auto-update, no
  scripts out of archives, no shell strings built from a path.
