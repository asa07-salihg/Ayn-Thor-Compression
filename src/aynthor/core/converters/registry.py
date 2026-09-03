"""Which converter handles which format.

Why
    One lookup table so the job runner never has to know the class names, and
    adding a format is one import plus one line rather than a change to the
    runner. The instances are shared and stateless apart from `on_progress`,
    which the runner sets and clears around each job.

Used by
    `ui.job_runner.JobRunner.run`.

Reference
    The formats themselves are catalogued in `core.formats`.
"""

from __future__ import annotations

from aynthor.core.converters.archive import SevenZipConverter
from aynthor.core.converters.base import BaseConverter
from aynthor.core.converters.chd import ChdmanConverter
from aynthor.core.converters.cso import MaxcsoConverter
from aynthor.core.converters.decrypt3ds import Decrypt3dsConverter
from aynthor.core.converters.nds import NdsTrimConverter
from aynthor.core.converters.nsz import NszConverter
from aynthor.core.converters.rvz import DolphinConverter
from aynthor.core.converters.wua import WuaConverter
from aynthor.core.converters.z3ds import Z3dsConverter
from aynthor.core.models import CompressionFormat

CONVERTERS: dict[CompressionFormat, BaseConverter] = {
    CompressionFormat.CHD: ChdmanConverter(),
    CompressionFormat.RVZ: DolphinConverter(),
    CompressionFormat.CSO: MaxcsoConverter(),
    CompressionFormat.Z3DS: Z3dsConverter(),
    CompressionFormat.NDS_TRIM: NdsTrimConverter(),
    CompressionFormat.NSZ: NszConverter(),
    CompressionFormat.SEVEN_ZIP: SevenZipConverter(),
    CompressionFormat.WUA: WuaConverter(),
    CompressionFormat.DEC_3DS: Decrypt3dsConverter(),
}


def get_converter(fmt: CompressionFormat) -> BaseConverter | None:
    return CONVERTERS.get(fmt)
