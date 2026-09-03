"""CHD, via MAME's chdman. PS1, PS2, PSP and Dreamcast disc images.

Why
    CHD is the one format that covers every optical system these emulators
    handle, and it collapses a cue/bin pair into a single file. chdman is the
    reference implementation; there is no library binding worth using, so we
    drive the command line.

Used by
    `core.converters.registry` for `CompressionFormat.CHD`.

Reference
    chdman command reference:
    https://docs.mamedev.org/tools/chdman.html
    Why PS2 gets zlib rather than zstd: the note on the PS2 entry in
    `core.presets`.
"""

from __future__ import annotations

from aynthor.core.converters.base import BaseConverter, failure, is_decompress
from aynthor.core.models import CompressionFormat, ConversionJob
from aynthor.core.system import run_tool, tool_path

# chdman's CD codecs have their own four-character names; the panel offers the
# familiar ones and they are translated here.
_CD_CODECS = {"zlib": "cdzl", "zstd": "cdzs", "lzma": "cdlz", "flac": "cdfl"}

_EXTRACT_FOR = {
    "createcd": "extractcd",
    "createdvd": "extractdvd",
    "createhd": "extracthd",
    "createraw": "extractraw",
}

# Track-based images. Anything else is treated as a single data image.
_CD_EXTENSIONS = {".cue", ".gdi", ".bin", ".toc"}

# chdman accepts at most four codecs and tries them in order per hunk.
_MAX_CODECS = 4


class ChdmanConverter(BaseConverter):
    format = CompressionFormat.CHD

    def convert(self, job: ConversionJob) -> tuple[bool, str]:
        error = self.validate(job)
        if error:
            return False, error

        chdman = tool_path("chdman")
        if not chdman.is_file():
            return False, f"chdman not found in {chdman.parent}. Install it from Tools."

        if is_decompress(job):
            return self._extract(chdman, job)
        return self._create(chdman, job)

    def _create(self, chdman, job: ConversionJob) -> tuple[bool, str]:
        opts = job.options
        chd_type = opts.get("chd_type", "auto")
        if chd_type == "auto":
            is_cd = job.input_path.suffix.lower() in _CD_EXTENSIONS
            chd_type = "createcd" if is_cd else "createdvd"

        args = [chd_type, "-i", str(job.input_path), "-o", str(job.output_path)]

        if opts.get("no_compression"):
            args += ["-c", "none"]
        else:
            selected = opts.get("codecs", [])
            if chd_type == "createcd":
                codecs = [_CD_CODECS[c] for c in selected if c in _CD_CODECS]
            else:
                # huff is a CD-only codec; offering it here would just fail.
                codecs = [c for c in selected if c != "huff"]
            if codecs:
                args += ["-c", ",".join(codecs[:_MAX_CODECS])]

        if hunk := opts.get("hunk_size", 0):
            args += ["-hs", str(hunk)]
        if processors := opts.get("num_processors", 0):
            args += ["-np", str(processors)]
        if opts.get("force"):
            args.append("-f")

        result = run_tool(chdman, args, on_output=self.emit)
        return (True, "CHD created.") if result.returncode == 0 else failure(result)

    def _extract(self, chdman, job: ConversionJob) -> tuple[bool, str]:
        chd_type = job.options.get("chd_type", "auto")
        command = _EXTRACT_FOR.get(chd_type)
        if command is None:
            # The output extension is the only hint left about what is inside:
            # a DVD image comes back as one .iso, a CD as a cue/bin pair.
            command = "extractdvd" if job.output_path.suffix.lower() == ".iso" else "extractcd"

        args = [command, "-i", str(job.input_path), "-o", str(job.output_path)]
        if job.options.get("force"):
            args.append("-f")

        result = run_tool(chdman, args, on_output=self.emit)
        return (True, "CHD opened.") if result.returncode == 0 else failure(result)
