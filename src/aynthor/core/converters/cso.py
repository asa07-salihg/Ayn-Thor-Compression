"""CSO / ZSO / DAX, via maxcso. PSP and PS2 ISO images.

Why
    An alternative to CHD for PSP: usually a little smaller, and PPSSPP reads
    it natively. maxcso is worth wrapping rather than writing our own because
    it tries several deflate implementations per block and keeps whichever wins
    -- which is where the extra few percent over other CSO tools comes from.

Used by
    `core.converters.registry` for `CompressionFormat.CSO`.

Reference
    maxcso options and the format notes:
    https://github.com/unknownbrackets/maxcso
    https://github.com/unknownbrackets/maxcso/blob/master/README_ZSO.md
"""

from __future__ import annotations

from aynthor.core.converters.base import BaseConverter, failure, is_decompress
from aynthor.core.models import CompressionFormat, ConversionJob
from aynthor.core.system import run_tool, tool_path


class MaxcsoConverter(BaseConverter):
    format = CompressionFormat.CSO

    def convert(self, job: ConversionJob) -> tuple[bool, str]:
        error = self.validate(job)
        if error:
            return False, error

        maxcso = tool_path("maxcso")
        if not maxcso.is_file():
            return False, f"maxcso not found in {maxcso.parent}. Install it from Tools."

        opts = job.options
        args: list[str] = []

        if is_decompress(job):
            args.append("--decompress")
        else:
            args.append(f"--format={opts.get('cso_format', 'cso1')}")
            if opts.get("fast"):
                args.append("--fast")
            # Each --use- adds one more deflate implementation to the contest.
            # More methods means a smaller file and a slower run.
            for method in opts.get("methods", []):
                args.append(f"--use-{method}")
            if block := opts.get("block_size", 0):
                args.append(f"--block={block}")

        if threads := opts.get("threads", 0):
            args.append(f"--threads={threads}")

        args += [str(job.input_path), "-o", str(job.output_path)]
        result = run_tool(maxcso, args, on_output=self.emit)
        return (True, "CSO done.") if result.returncode == 0 else failure(result)
