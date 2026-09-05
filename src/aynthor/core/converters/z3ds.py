"""ZCCI / ZCIA, via rom-converto, with two fallbacks. Nintendo 3DS.

Why
    Three engines exist for this format and none of them covers both
    directions well, so this converter picks per direction:

    - Compress prefers `rom-converto ctr compress`: it exposes a zstd level and
      refuses a still-encrypted ROM. `z3ds_compressor` (the reference Azahar
      compressor) is the fallback; it has fixed settings and will happily write
      a useless archive from an encrypted ROM, which is why the encryption
      check below runs before either engine is chosen.
    - Open prefers rom-converto too, but falls back to the container decoder in
      `core.ctr.z3ds`. That path is pure Python, so opening a file the app made
      never depends on a download.

Used by
    `core.converters.registry` for `CompressionFormat.Z3DS`.

Reference
    https://github.com/DevYukine/rom-converto  (`ctr compress` / `ctr decompress`)
    https://github.com/energeticokay/z3ds_compress
    Container layout: `core.ctr.z3ds`
"""

from __future__ import annotations

from aynthor.core.converters.base import BaseConverter, failure, is_decompress, size_progress
from aynthor.core.ctr import ncch
from aynthor.core.ctr import z3ds as container
from aynthor.core.models import CompressionFormat, ConversionJob
from aynthor.core.system import run_tool, tool_path


def _compress_hint(tool_output: str) -> str:
    """Translate rom-converto's two "cannot compress" errors.

    They mean different things and must not be collapsed: one is a ROM that is
    definitely still encrypted, the other is a header rom-converto could not
    parse at all -- a damaged or unexpected container, not necessarily crypto.
    """
    lowered = (tool_output or "").lower()
    if "appears to be encrypted" in lowered:
        return ("This ROM is still encrypted. Run it through Decrypt 3DS first, "
                "then compress the decrypted file.")
    if "whether the input rom is encrypted" in lowered:
        return ("The ROM header could not be read, so its encryption state is "
                "unknown. Try Decrypt 3DS, or re-dump the cart.")
    return ""


def _encryption_note(path) -> str:
    """A ZCCI made from an encrypted ROM opens back into an encrypted ROM.

    Saying so here beats letting the user find out when re-compression is
    refused several steps later.
    """
    if ncch.is_encrypted(path):
        return "  (still encrypted: run Decrypt 3DS before compressing)"
    return ""


class Z3dsConverter(BaseConverter):
    format = CompressionFormat.Z3DS

    def convert(self, job: ConversionJob) -> tuple[bool, str]:
        error = self.validate(job)
        if error:
            return False, error
        return self._open(job) if is_decompress(job) else self._compress(job)

    # ------------------------------------------------------------------ compress

    def _compress(self, job: ConversionJob) -> tuple[bool, str]:
        if container.is_z3ds_file(job.input_path):
            return False, "This is already a Z3DS file. Switch Mode to Open to decompress it."

        if not job.options.get("allow_encrypted") and ncch.is_encrypted(job.input_path):
            return False, (
                "This ROM is still encrypted, and encrypted data does not compress. "
                "Run it through Decrypt 3DS first, or tick 'Allow encrypted' to "
                "compress it anyway."
            )

        converto = tool_path("rom-converto")
        if converto.is_file():
            return self._compress_with_converto(converto, job)

        fallback = tool_path("z3ds_compressor")
        if not fallback.is_file():
            return False, ("No 3DS compressor installed. Install rom-converto or "
                           "z3ds_compress from Tools.")

        args = [str(job.input_path), str(job.output_path)]
        if frame_size := job.options.get("frame_size", 0):
            args += ["--frame-size", str(frame_size)]
        result = run_tool(fallback, args, on_output=self.emit)
        return (True, "ZCCI done.") if result.returncode == 0 else failure(result)

    def _compress_with_converto(self, converto, job: ConversionJob) -> tuple[bool, str]:
        args = ["--no-update-check", "ctr", "compress",
                str(job.input_path), str(job.output_path), "--force"]
        if level := job.options.get("level", 0):
            args += ["--level", str(level)]
        if job.options.get("allow_encrypted"):
            args.append("--allow-encrypted")

        result = run_tool(converto, args, on_output=self.emit)
        if result.returncode == 0:
            return True, "ZCCI done."

        detail = failure(result)[1]
        hint = _compress_hint(detail)
        # Keep the tool's own words alongside ours: the hint is guidance, not a
        # replacement for what actually went wrong.
        return False, f"{hint}\n{detail}" if hint else detail

    # ---------------------------------------------------------------------- open

    def _open(self, job: ConversionJob) -> tuple[bool, str]:
        try:
            header = container.read_header(job.input_path)
        except container.Z3dsError as exc:
            return False, str(exc)

        output = job.output_path
        if job.input_path.suffix.lower() not in container.CONTAINER_EXTENSIONS:
            # A generic .z3ds does not encode what it holds; the header does.
            output = output.with_suffix(container.original_extension(job.input_path, header))
        if output.resolve() == job.input_path.resolve():
            output = output.with_name(f"{output.stem}-decompressed{output.suffix}")
        if output != job.output_path and output.exists():
            # The conflict policy was applied to the path the queue predicted.
            # This one comes from the header of the file being opened, so it
            # was never checked, and both engines below write with overwrite
            # already on: a `.z3ds` claiming CIA magic destroyed the user's
            # `Game.cia` with Skip selected.
            return False, (f"{output.name} already exists. This file expands to that "
                           "name, which the conflict policy never saw, so nothing "
                           "was written.")
        job.output_path = output

        converto = tool_path("rom-converto")
        if converto.is_file():
            args = ["--no-update-check", "ctr", "decompress",
                    str(job.input_path), str(output), "--force"]
            # rom-converto draws its progress bar only on a terminal, so the
            # output file's size is the only signal available here.
            with size_progress(output, header.uncompressed_size, self.on_progress):
                result = run_tool(converto, args, on_output=self.emit)
            if result.returncode != 0:
                # A real decoding failure should surface as-is rather than being
                # retried with the fallback, which would fail the same way.
                return failure(result)
            if self.on_progress:
                self.on_progress(100)
            return True, f"Opened -> {output.name}{_encryption_note(output)}"

        try:
            written = container.decompress(job.input_path, output, self.emit)
        except container.Z3dsError as exc:
            return False, str(exc)
        return True, f"Opened -> {written.name}{_encryption_note(written)}"
