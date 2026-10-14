"""NSZ / XCZ, via the nsz package. Nintendo Switch titles.

NSZ recompresses the encrypted NCA contents with zstd and leaves every
signature in place, so installers still accept the result -- that is the
whole point of the format, and why it needs the console keys the user
supplies. The app never ships keys; see SECURITY.md.

nsz runs out of process rather than as a library call because it uses
`multiprocessing` internally and writes to global state during a run;
importing it into the GUI process made a cancelled job leave worker
processes behind. The passthrough is `core.nsz_runner`.

https://github.com/nicoboss/nsz
NCA container layout: https://switchbrew.org/wiki/NCA
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from aynthor.core.converters.base import BaseConverter, failure, is_decompress
from aynthor.core.models import CompressionFormat, ConversionJob
from aynthor.core.nsz_runner import nsz_command, staged_keys
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
        try:
            job.output_path.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(
                prefix=".aynthor-nsz-", dir=job.output_path.parent))
        except OSError as exc:
            return False, f"Could not prepare the output folder: {exc}"

        try:
            args = (self._decompress_args(job, staging) if decompressing
                    else self._compress_args(job, staging))
            with staged_keys(keys_file, workdir):
                result = run_tool(
                    command[0], [*command[1:], *args],
                    cwd=workdir, env=extra_env, on_output=self.emit,
                )
            if result.returncode != 0:
                return failure(result)
            return self._collect(job, staging)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _collect(job: ConversionJob, staging: Path) -> tuple[bool, str]:
        """Move what nsz wrote to the path the queue promised.

        nsz names its own output, from the *input* stem, and only takes a
        directory. So `Ys X Nordics [0100BAC01E57E800][v0].nsp` came out as
        `Ys X Nordics [0100BAC01E57E800][v0].nsz` while the queue, the game
        folder and the conflict policy had all agreed on `Ys X Nordics.nsz`.
        Two things went wrong with that. The folder ES-DE launches is the one
        holding a file with the folder's own name, and that file was never
        written, so the title did not appear. And with the policy set to
        rename, the queue had moved the output aside to `Game_1.nsz` while
        nsz still wrote `Game.nsz` -- straight over the file the policy
        existed to protect.

        Letting nsz name a file inside a private folder and renaming it
        afterwards keeps its naming and honours the policy. The rename is on
        the same volume, so nothing is copied twice.
        """
        produced = sorted(
            (path for path in staging.rglob("*") if path.is_file()),
            key=lambda path: path.stat().st_size,
            reverse=True,
        )
        if not produced:
            return False, "nsz reported success but wrote nothing."
        wanted = job.output_path.suffix.lower()
        chosen = next(
            (path for path in produced if path.suffix.lower() == wanted), produced[0])
        try:
            if job.output_path.exists():
                job.output_path.unlink()
            os.replace(chosen, job.output_path)
        except OSError as exc:
            return False, f"Could not move the result into place: {exc}"
        return True, "NSZ done."

    @staticmethod
    def _decompress_args(job: ConversionJob, staging: Path) -> list[str]:
        args = ["-D"]
        if threads := job.options.get("threads", 0):
            args += ["-t", str(threads)]
        # nsz names the output itself from the input stem, so it takes a
        # directory rather than a file path. `_collect` renames afterwards.
        return [*args, "-o", str(staging), str(job.input_path)]

    @staticmethod
    def _compress_args(job: ConversionJob, staging: Path) -> list[str]:
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
        return [*args, "-o", str(staging), str(job.input_path)]
