"""The choices the user has made, in one object.

Why
    There is no "currently selected format" in this app. Every queued row
    carries its own target, so settings are stored per format rather than for
    whichever one happens to be highlighted. That removes a whole class of
    confusion the previous design had: changing a value in one place and having
    it silently apply, or not apply, to rows that were already queued.

    What is left global is what genuinely is: where output goes, what to do
    about an existing file, whether to delete sources, and where the Switch
    keys live.

Used by
    `ui.settings_dialog` (writes), `core.jobs.build_jobs` and
    `ui.queue_view` (read), `ui.main_window` (owns the single instance).

Reference
    Persisting these between sessions is `ui.state`, kept separate because
    `core` must not depend on Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aynthor.core.models import CompressionFormat


@dataclass
class FormatSettings:
    output_dir: str = ""

    # The user's ES-DE ROMs folder. When set, a converted file is written to
    # the platform folder it belongs in rather than beside its input, which is
    # what someone filling a card actually wants: point the app at a fresh
    # download, tell it the platform, and the result lands where the emulator
    # will look for it. Overrides `output_dir` for any row that knows its
    # platform; a row that does not falls back to the ordinary rules.
    esde_root: str = ""

    # skip | overwrite | rename. Skip by default so re-running over a finished
    # folder does nothing rather than redoing hours of work.
    on_conflict: str = "skip"

    delete_source: bool = False

    # Switch titles arrive as base plus update plus DLC; this groups each set
    # into its own output folder so an installer sees them together.
    switch_game_subdirs: bool = False

    keys_path: str = ""

    # Per-format defaults, as the format's own options panel produced them.
    # The converter is the schema: each one needs a different set of flags and
    # only its panel knows which.
    options: dict[CompressionFormat, dict] = field(default_factory=dict)

    def for_format(self, fmt: CompressionFormat | None) -> dict:
        if fmt is None:
            return {}
        return dict(self.options.get(fmt, {}))
