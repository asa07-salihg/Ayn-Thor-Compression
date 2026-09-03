"""NSZ / XCZ, via the nsz package. Nintendo Switch titles.

Why
    NSZ recompresses the encrypted NCA contents with zstd and leaves every
    signature in place, so installers still accept the result -- that is the
    whole point of the format, and why it needs the console keys the user
    supplies. The app never ships keys; see SECURITY.md.

    nsz runs out of process rather than as a library call because it uses
    `multiprocessing` internally and writes to global state during a run;
    importing it into the GUI process made a cancelled job leave worker
    processes behind. The passthrough is `core.nsz_runner`.

Used by
    `core.converters.registry` for `CompressionFormat.NSZ`.

Reference
    https://github.com/nicoboss/nsz
    NCA container layout: https://switchbrew.org/wiki/NCA
"""

from __future__ import annotations

from pathlib import Path

from aynthor.core.converters.base import BaseConverter, failure, is_decompress
from aynthor.core.models import CompressionFormat, ConversionJob
from aynthor.core.nsz_runner import nsz_command, stage_keys
from aynthor.core.system import find_prod_keys, run_tool

_ALREADY_COMPRESSED = {".nsz", ".xcz"}


class NszConverter(BaseConverter):
    format = CompressionFormat.NSZ

    def convert(self, job: ConversionJob) -> tuple[bool, str]:
        error = self.validate(job)
        if error:
            return False, error

        opts = job.options
        keys_setting = opts.get("keys_path")
        keys_file = Path(keys_setting) if keys_setting else find_prod_keys()
        if not keys_file or not keys_file.is_file():
            return False, (
                "prod.keys not found. Put it next to the app, in ~/.switch/, or "
                "select it in the NSZ options panel."
            )

        decompressing = is_decompress(job)
        if decompressing and job.input_path.suffix.lower() not in _ALREADY_COMPRESSED:
            return False, "Open works on .nsz and .xcz. Use Compress for .nsp and .xci."

        command, workdir, extra_env = nsz_command()
        stage_keys(keys_file, workdir)

        args = self._decompress_args(job) if decompressing else self._compress_args(job)
        result = run_tool(
            command[0], [*command[1:], *args],
            cwd=workdir, env=extra_env, on_output=self.emit,
        )
        return (True, "NSZ done.") if result.returncode == 0 else failure(result)

    @staticmethod
    def _decompress_args(job: ConversionJob) -> list[str]:
        args = ["-D"]
        if threads := job.options.get("threads", 0):
            args += ["-t", str(threads)]
        # nsz names the output itself from the title metadata, so it takes a
        # directory rather than a file path.
        return [*args, "-o", str(job.output_path.parent), str(job.input_path)]

    @staticmethod
    def _compress_args(job: ConversionJob) -> list[str]:
        opts = job.options
        args = ["-C", "-l", str(opts.get("level", 18))]
        if opts.get("long"):
            args.append("-L")

        mode = opts.get("comp_mode", "auto")
        if mode == "block":
            # Block mode is what makes an NSZ seekable, which is what lets an
            # emulator stream it instead of unpacking it first.
            args.append("-B")
            if block_exponent := opts.get("bs_exp"):
                args += ["-s", str(block_exponent)]
        elif mode == "solid":
            args.append("-S")

        if threads := opts.get("threads", 0):
            args += ["-t", str(threads)]
        if parallel := opts.get("multi"):
            args += ["-m", str(parallel)]
        return [*args, "-o", str(job.output_path.parent), str(job.input_path)]
