"""7z and ZIP, via 7-Zip. Cartridge ROMs and arcade romsets.

Why
    SNES, Mega Drive, GB and GBA ROMs are plain uncompressed data and give up a
    lot to a general-purpose compressor. RetroArch opens 7z transparently, so
    there is no cost to the user. FBNeo and MAME are the exception: those cores
    expect a zipped romset and will not look inside a 7z, which is why the
    archive type is a setting rather than a constant.

Used by
    `core.converters.registry` for `CompressionFormat.SEVEN_ZIP`.

Reference
    7-Zip command line switches:
    https://documentation.help/7-Zip/
"""

from __future__ import annotations

from aynthor.core.converters.base import BaseConverter, failure, is_decompress
from aynthor.core.models import CompressionFormat, ConversionJob
from aynthor.core.system import run_tool, tool_path


class SevenZipConverter(BaseConverter):
    format = CompressionFormat.SEVEN_ZIP

    def convert(self, job: ConversionJob) -> tuple[bool, str]:
        error = self.validate(job)
        if error:
            return False, error

        seven_zip = tool_path("7za")
        if not seven_zip.is_file():
            return False, f"7za not found in {seven_zip.parent}. Install it from Tools."

        opts = job.options

        if is_decompress(job):
            # An archive expands into a folder; `suggest_output_path` already
            # produced an extensionless path for it.
            out_dir = job.output_path if job.output_path.suffix == "" else job.output_path.parent
            out_dir.mkdir(parents=True, exist_ok=True)
            args = ["x", str(job.input_path), f"-o{out_dir}", "-y"]
        else:
            archive_type = opts.get("archive_type", "7z")
            args = ["a", f"-t{archive_type}", f"-mx={opts.get('level', 9)}"]
            if method := opts.get("method"):
                args.append(f"-m0={method}")
            if archive_type == "7z":
                # Solid helps when several ROMs share an archive and costs
                # nothing when only one does.
                args.append(f"-ms={'on' if opts.get('solid', True) else 'off'}")
            threads = opts.get("threads", 0)
            args.append(f"-mmt={threads}" if threads else "-mmt=on")
            args += [str(job.output_path), str(job.input_path)]

        result = run_tool(seven_zip, args, on_output=self.emit)
        return (True, "Archive done.") if result.returncode == 0 else failure(result)
