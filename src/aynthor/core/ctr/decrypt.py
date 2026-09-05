"""Decrypt 3DS carts and CIAs by driving the Batch CIA 3DS Decryptor tools.

Why
    A Python port of the Batch CIA 3DS Decryptor Redux batch script, because
    the original is a Windows .bat that expects to be double-clicked and cannot
    report progress or errors back into a GUI. The sequence it implements is
    not obvious and cannot be shortened:

        ctrtool  read the title id, version and crypto key (needs seeddb.bin)
        decrypt  dump the decrypted NCCH partitions
        makerom  repack those partitions into a decrypted .cci or .cia

    The three tools plus seeddb.bin are copied into a private working directory
    first. That is not tidiness: decrypt.exe writes its output next to itself,
    so running it from the shared tools folder would scatter multi-gigabyte
    .ncch intermediates among the binaries.

Used by
    `core.converters.decrypt3ds.Decrypt3dsConverter`.

Reference
    https://github.com/xxmichibxx/Batch-CIA-3DS-Decryptor-Redux
    Title id prefixes (what makes a title a game, patch, DLC or DSiWare):
    https://www.3dbrew.org/wiki/Title_list
    makerom: https://github.com/3DSGuy/Project_CTR
"""

from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from aynthor.core.system import app_data_dir, run_tool, tools_dir

_HASH_CHUNK = 256 * 1024

Emit = Callable[[str], None]

REQUIRED_TOOLS = ("ctrtool.exe", "decrypt.exe", "makerom.exe", "seeddb.bin")

_TITLE_ID_RE = re.compile(r"Title\s?id:\s*([0-9a-fA-F]{16})")
_VERSION_RE = re.compile(r"TitleVersion:\s*(\d+)")
_CRYPTO_RE = re.compile(r"Crypto Key:\s*(.+)")
_CONTENT_ID_RE = re.compile(r"ContentId:\s*([0-9a-fA-F]{8})")

# .3ds partition name -> CCI partition index (mirrors the batch script)
_3DS_PARTITIONS = {
    "Main": 0,
    "Manual": 1,
    "DownloadPlay": 2,
    "Partition4": 3,
    "Partition5": 4,
    "Partition6": 5,
    "N3DSUpdateData": 6,
    "UpdateData": 7,
}

_SYSTEM_PREFIXES = ("00040010", "0004001b", "00040030", "0004009b",
                    "000400db", "00040130", "00040138")
_TWL_PREFIXES = ("00048005", "0004800f", "00048004")


class DecryptError(RuntimeError):
    pass


def workdir() -> Path:
    path = app_data_dir() / "3ds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def missing_tools() -> list[str]:
    """Which of the required binaries are absent. Empty means ready to run."""
    tools = tools_dir()
    return [name for name in REQUIRED_TOOLS if not (tools / name).is_file()]


def tools_ready() -> bool:
    return not missing_tools()


def _digest(path: Path) -> str:
    handle = hashlib.sha256()
    with path.open("rb") as opened:
        for chunk in iter(lambda: opened.read(_HASH_CHUNK), b""):
            handle.update(chunk)
    return handle.hexdigest()


def _stage_tools(dest: Path) -> None:
    tools = tools_dir()
    for name in REQUIRED_TOOLS:
        src = tools / name
        if not src.is_file():
            raise DecryptError(f"{name} not found. Download the 3DS Decryptor from Tools.")
        target = dest / name
        # Compared by content, not by size. This directory is a fixed,
        # user-writable path and the tools are executed from it, so a stale
        # copy from an older pin -- or anything of the right length dropped
        # there -- used to run forever, and no amount of verifying `tools/`
        # would notice. The verified copy is the only one allowed to survive.
        if not target.is_file() or _digest(target) != _digest(src):
            target.unlink(missing_ok=True)
            shutil.copy2(src, target)


def _clean_ncch(dest: Path) -> None:
    for leftover in dest.glob("*.ncch"):
        leftover.unlink(missing_ok=True)
    for leftover in dest.glob("*.app*"):
        leftover.unlink(missing_ok=True)


def analyze(rom: Path, work: Path) -> tuple[str, int, str]:
    """Return (title_id, title_version, crypto_key_line) from ctrtool."""
    result = run_tool(
        work / "ctrtool.exe",
        ["--seeddb=seeddb.bin", str(rom)],
        cwd=work,
    )
    text = (result.stdout or "") + (result.stderr or "")
    if "ERROR" in text and "Title id" not in text:
        raise DecryptError("Invalid or unreadable CIA/3DS file.")
    title_id = _TITLE_ID_RE.search(text)
    version = _VERSION_RE.search(text)
    crypto = _CRYPTO_RE.search(text)
    return (
        title_id.group(1) if title_id else "",
        int(version.group(1)) if version else 0,
        crypto.group(1).strip() if crypto else "",
    )


def content_ids(rom: Path, work: Path) -> list[str]:
    result = run_tool(work / "ctrtool.exe", ["--seeddb=seeddb.bin", str(rom)], cwd=work)
    return _CONTENT_ID_RE.findall((result.stdout or "") + (result.stderr or ""))


def _dump_ncch(rom: Path, work: Path, emit: Emit) -> list[Path]:
    """Run decrypt.exe; it writes '<stem>.<part>.ncch' files next to itself."""
    _clean_ncch(work)
    emit(f"Decrypting partitions: {rom.name}")
    result = run_tool(work / "decrypt.exe", [str(rom)], cwd=work)
    ncch = sorted(work.glob("*.ncch"))
    if not ncch:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        reason = f" ({detail[-1]})" if detail else ""
        raise DecryptError("decrypt.exe produced no output." + reason)
    return ncch


def _part_key(path: Path) -> str:
    # "<stem>.<Part>.ncch" -> "<Part>"  (stem may itself contain dots)
    return path.suffixes[-2].lstrip(".") if len(path.suffixes) >= 2 else path.stem


def decrypt_cart(rom: Path, output: Path, emit: Emit) -> Path:
    """Decrypt a .3ds cartridge image into a trimmed, decrypted .cci."""
    work = workdir()
    _stage_tools(work)
    try:
        title_id, version, crypto = analyze(rom, work)
        if "None" in crypto:
            raise DecryptError("Already decrypted (Crypto Key: None).")
        emit(f"Title {title_id} v{version}")
        ncch = _dump_ncch(rom, work, emit)

        args = ["-f", "cci", "-ignoresign", "-target", "p", "-o", str(output)]
        for part in ncch:
            index = _3DS_PARTITIONS.get(_part_key(part))
            if index is None:
                continue
            args += ["-i", f"{part.name}:{index}:{index}"]
        emit("Rebuilding CCI...")
        run_tool(work / "makerom.exe", args, cwd=work)
        if not output.is_file():
            raise DecryptError("makerom failed to build the CCI.")
        return output
    finally:
        _clean_ncch(work)


def decrypt_cia(rom: Path, output: Path, emit: Emit, *, to_cci: bool = False) -> Path:
    """Decrypt a .cia into a decrypted .cia (games optionally converted to .cci)."""
    work = workdir()
    _stage_tools(work)
    try:
        title_id, version, crypto = analyze(rom, work)
        prefix = title_id[:8].lower()
        if prefix in _TWL_PREFIXES:
            raise DecryptError("TWL (DSiWare) titles are not supported. "
                               "Play them with melonDS instead.")
        if "None" in crypto:
            raise DecryptError("Already decrypted (Crypto Key: None).")
        if "Secure" not in crypto:
            raise DecryptError(f"Unsupported CIA type (title {title_id or '?'}).")
        emit(f"Title {title_id} v{version}")

        is_patch = prefix == "0004000e"
        is_dlc = prefix == "0004008c"
        is_game = prefix == "00040000"
        is_demo = prefix == "00040002"
        is_system = prefix in _SYSTEM_PREFIXES
        if not (is_patch or is_dlc or is_game or is_demo or is_system):
            raise DecryptError(f"Unknown CIA type (title {title_id}).")

        ids = content_ids(rom, work) if (is_patch or is_dlc) else []
        ncch = _dump_ncch(rom, work, emit)

        args = ["-f", "cia"]
        if is_dlc:
            args.append("-dlc")
        args += ["-ignoresign", "-target", "p", "-o", str(output)]
        for i, part in enumerate(ncch):
            if is_patch or is_dlc:
                content_id = int(ids[i], 16) if i < len(ids) else i
                args += ["-i", f"{part.name}:{i}:{content_id}"]
            else:
                args += ["-i", f"{part.name}:{i}:{i}"]
        args += ["-ver", str(version)]
        emit("Rebuilding CIA...")
        run_tool(work / "makerom.exe", args, cwd=work)
        if not output.is_file():
            raise DecryptError("makerom failed to build the CIA.")

        if to_cci and is_game:
            cci_out = output.with_suffix(".cci")
            if cci_out.exists():
                # The conflict policy was applied to `output`, never to this.
                # Writing here anyway overwrote a file the user had, with Skip
                # selected, and then deleted the one the policy did approve.
                emit(f"{cci_out.name} already exists; keeping the decrypted CIA.")
                return output
            emit("Converting to CCI...")
            run_tool(work / "makerom.exe", ["-ciatocci", str(output), "-o", str(cci_out)], cwd=work)
            if cci_out.is_file():
                output.unlink(missing_ok=True)
                return cci_out
            emit("CCI conversion failed; keeping the decrypted CIA.")
        return output
    finally:
        _clean_ncch(work)
