"""RVZ, via DolphinTool. GameCube and Wii disc images.

Why
    RVZ is Dolphin's own format and the only one that both compresses and
    scrubs: Nintendo's discs are padded to a fixed size with junk data, and RVZ
    drops it. GCZ and WBFS do not, which is why a GameCube ISO can lose most of
    its size here and almost none elsewhere.

Used by
    `core.converters.registry` for `CompressionFormat.RVZ`.

Reference
    DolphinTool usage:
    https://github.com/dolphin-emu/dolphin/tree/master/Source/Core/DolphinTool
"""

from __future__ import annotations

from aynthor.core.converters.base import BaseConverter, failure, is_decompress
from aynthor.core.models import CompressionFormat, ConversionJob
from aynthor.core.system import run_tool, tool_path

# GCZ predates the codec system and always uses its own deflate.
_TAKES_CODEC = {"rvz", "wia"}
_TAKES_BLOCK_SIZE = {"rvz", "wia", "gcz"}


class DolphinConverter(BaseConverter):
    format = CompressionFormat.RVZ

    def convert(self, job: ConversionJob) -> tuple[bool, str]:
        error = self.validate(job)
        if error:
            return False, error

        dolphin = tool_path("DolphinTool")
        if not dolphin.is_file():
            return False, (
                f"DolphinTool not found in {dolphin.parent}. Install it from Tools, "
                "or point Tools at the copy inside your Dolphin install."
            )

        opts = job.options
        decompressing = is_decompress(job)
        out_format = "iso" if decompressing else opts.get("out_fmt", "rvz")

        args = ["convert", "-i", str(job.input_path), "-o", str(job.output_path),
                "-f", out_format]

        if opts.get("scrub"):
            args.append("-s")

        if not decompressing:
            if out_format in _TAKES_BLOCK_SIZE and (block := opts.get("block_size")):
                args += ["-b", str(block)]
            if out_format in _TAKES_CODEC:
                codec = opts.get("codec", "zstd")
                args += ["-c", codec]
                if codec != "none":
                    args += ["-l", str(opts.get("level", 5))]

        result = run_tool(dolphin, args, on_output=self.emit)
        if result.returncode != 0:
            return failure(result)
        return True, f"{out_format.upper()} done."
