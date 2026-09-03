"""WUA, via rom-converto. Wii U titles for Cemu.

Why
    A Wii U title is normally a folder tree, or a disc image plus separate
    update and DLC folders. WUA packs the lot into one archive that Cemu mounts
    as a single title, which is the difference between a browsable game list
    and a pile of directories. There is no reverse direction: Cemu reads WUA
    and nothing converts back, so Open is refused rather than silently doing
    something else.

Used by
    `core.converters.registry` for `CompressionFormat.WUA`.

Reference
    https://github.com/DevYukine/rom-converto  (`wup compress`)
    A .wud/.wux disc image is encrypted with a per-disc key that is not part of
    the image.
"""

from __future__ import annotations

from pathlib import Path

from aynthor.core.converters.base import BaseConverter, failure, is_decompress
from aynthor.core.models import CompressionFormat, ConversionJob
from aynthor.core.system import run_tool, tool_path

# Raw disc images. NUS and loadiine folder dumps carry their own keys.
_NEEDS_DISC_KEY = {".wud", ".wux"}


class WuaConverter(BaseConverter):
    format = CompressionFormat.WUA

    def convert(self, job: ConversionJob) -> tuple[bool, str]:
        error = self.validate(job)
        if error:
            return False, error

        if is_decompress(job):
            return False, "WUA cannot be unpacked: Cemu reads it directly and no tool reverses it."

        converto = tool_path("rom-converto")
        if not converto.is_file():
            return False, f"rom-converto not found in {converto.parent}. Install it from Tools."

        opts = job.options
        args = ["wup", "compress", "-o", str(job.output_path)]

        if (level := opts.get("level")) is not None and level:
            args += ["-l", str(level)]

        if job.input_path.suffix.lower() in _NEEDS_DISC_KEY:
            key_error = self._resolve_key(job, args)
            if key_error:
                return False, key_error

        args.append(str(job.input_path))
        result = run_tool(converto, args, on_output=self.emit)
        return (True, "WUA created.") if result.returncode == 0 else failure(result)

    @staticmethod
    def _resolve_key(job: ConversionJob, args: list[str]) -> str | None:
        """Append --key, or explain what is missing. None means all is well."""
        chosen = job.options.get("key_path")
        if chosen:
            key_file = Path(chosen)
            if not key_file.is_file():
                return f"Disc key not found: {chosen}"
            args += ["--key", str(key_file)]
            return None

        # rom-converto finds a sibling key on its own; we only check so the
        # error arrives before the run rather than several minutes into it.
        disc = job.input_path
        if disc.with_suffix(".key").is_file() or (disc.parent / "game.key").is_file():
            return None
        return (
            "This disc image needs its key. Put <name>.key or game.key next to it, "
            "or select one in the options panel."
        )
