"""The data every other module passes around: formats, modes, jobs, queue rows.

Why
    These four types are the only things `core` and `ui` both need to agree on.
    Keeping them in one leaf module means `core` never has to import from `ui`
    to describe a queue row, and `ui` never has to import a converter to
    describe a job. Before this module existed, `ConversionMode` was declared
    twice (in `types.py` and in `conversion_modes.py`) and `QueueItem` lived in
    a Qt widget file that `core.jobs` had to import under `TYPE_CHECKING`.

Used by
    Everything. `core.formats`, `core.jobs`, `core.presets`, every converter,
    and every widget under `ui/`.

Reference
    No external spec: this is the app's own vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class CompressionFormat(str, Enum):
    """A target the app can produce.

    `str` mixin so a value survives a round trip through Qt item data, which
    stores a plain `QVariant` and would otherwise hand back an unusable object.
    """

    CHD = "chd"
    RVZ = "rvz"
    CSO = "cso"
    Z3DS = "z3ds"
    NDS_TRIM = "nds_trim"
    NSZ = "nsz"
    SEVEN_ZIP = "7z"
    WUA = "wua"
    DEC_3DS = "3ds_dec"
    UNKNOWN = "unknown"


class ConversionMode(str, Enum):
    """Direction of travel.

    DECOMPRESS is labelled "Open" in the interface: for most of these formats
    the user is not unpacking an archive, they are getting their disc image
    back so another tool can read it.
    """

    COMPRESS = "compress"
    DECOMPRESS = "decompress"


@dataclass
class ConversionJob:
    """One file, one tool invocation.

    `options` is a flat dict rather than a typed object on purpose: each
    converter needs a different set of flags, and the panel that collects them
    (`ui.option_panels`) is the only place that knows which. The converter is
    the schema.
    """

    input_path: Path
    output_path: Path
    format: CompressionFormat
    options: dict = field(default_factory=dict)
    status: str = "pending"
    message: str = ""
    input_size: int = 0
    output_size: int = 0


@dataclass
class QueueItem:
    """One row of the queue, before it becomes a job.

    A row and a job are not the same thing: a row can be skipped (its output
    already exists and the conflict policy says "skip"), and a row keeps
    display-only fields such as the game grouping that a converter never sees.
    """

    path: Path
    format: CompressionFormat | None
    mode: ConversionMode
    output: Path
    tool_options: dict | None = None
    game_group: str = ""
    content_type: str = ""
    status: str = "Waiting"
    message: str = ""
