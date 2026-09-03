"""Decrypt 3DS carts and CIAs, via the Batch CIA 3DS Decryptor Redux tools.

Why
    A cart dumped from a console is encrypted. Emulators decrypt on the fly, so
    the encryption is invisible until you try to compress the file -- and
    encrypted bytes do not compress, so ZCCI on an encrypted ROM saves nothing.
    This step therefore has to run first, and it is exposed as its own format
    in the sidebar rather than hidden inside the ZCCI path, because the
    decrypted file is useful on its own.

Used by
    `core.converters.registry` for `CompressionFormat.DEC_3DS`.

Reference
    https://github.com/xxmichibxx/Batch-CIA-3DS-Decryptor-Redux
    NCCH and NCSD layout: https://www.3dbrew.org/wiki/NCSD
"""

from __future__ import annotations

from aynthor.core.converters.base import BaseConverter
from aynthor.core.ctr import decrypt
from aynthor.core.models import CompressionFormat, ConversionJob

# .3ds and .cci are the same NCSD container under two names.
_CART_EXTENSIONS = {".3ds", ".cci"}


class Decrypt3dsConverter(BaseConverter):
    format = CompressionFormat.DEC_3DS

    def convert(self, job: ConversionJob) -> tuple[bool, str]:
        error = self.validate(job)
        if error:
            return False, error

        missing = decrypt.missing_tools()
        if missing:
            return False, ("Missing 3DS decryptor tools: "
                           f"{', '.join(missing)}. Install them from Tools.")

        try:
            if job.input_path.suffix.lower() in _CART_EXTENSIONS:
                output = decrypt.decrypt_cart(job.input_path, job.output_path, self.emit)
            else:
                output = decrypt.decrypt_cia(
                    job.input_path,
                    job.output_path,
                    self.emit,
                    to_cci=bool(job.options.get("to_cci")),
                )
        except decrypt.DecryptError as exc:
            return False, str(exc)

        job.output_path = output
        return True, f"Decrypted -> {output.name}"
