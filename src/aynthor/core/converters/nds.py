"""Nintendo DS cart trimming, via ndstrim.

Why
    melonDS will not read an archive, so 7z is not an option for DS. The only
    saving left is the unused tail of the cart image, which the header records
    the real end of. This is the one "compression" format in the app that
    modifies a ROM in place rather than producing a new container, so a copy is
    made first whenever the output path differs from the input.

Used by
    `core.converters.registry` for `CompressionFormat.NDS_TRIM`.

Reference
    https://github.com/Nemris/ndstrim
    Cart header layout (the used-size field this relies on):
    https://problemkaputt.de/gbatek.htm#dscartridgeheader
"""

from __future__ import annotations

import shutil

from aynthor.core.converters.base import BaseConverter, failure
from aynthor.core.models import CompressionFormat, ConversionJob
from aynthor.core.system import run_tool, tool_path


class NdsTrimConverter(BaseConverter):
    format = CompressionFormat.NDS_TRIM

    def convert(self, job: ConversionJob) -> tuple[bool, str]:
        error = self.validate(job)
        if error:
            return False, error

        ndstrim = tool_path("ndstrim")
        if not ndstrim.is_file():
            return False, f"ndstrim not found in {ndstrim.parent}. Install it from Tools."

        target = job.output_path
        if target.resolve() != job.input_path.resolve():
            # ndstrim only edits in place, so trimming to a different location
            # means copying there first and trimming the copy.
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(job.input_path, target)

        result = run_tool(ndstrim, ["-i", str(target)], on_output=self.emit)
        return (True, "NDS trimmed.") if result.returncode == 0 else failure(result)
