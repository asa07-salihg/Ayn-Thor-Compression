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

    # Give every game its own folder, named exactly like its primary file:
    # `psx/Game.chd/Game.chd`. ES-DE shows such a folder as one game and
    # launches the file inside that matches the folder's name, and extra discs,
    # updates and DLC sit beside it under their own names. Replaces the older
    # Switch-only grouping, which did the same thing for one platform.
    game_folders: bool = False

    # Empty platform and game folders (`psx/` with no ROMs yet, `Game.chd/`
    # waiting for a dump) can sit in the queue as drop targets. Off by default
    # so a freshly copied ES-DE tree of empty folders does not bury the files.
    show_empty_folders: bool = False

    keys_path: str = ""

    # Per-format defaults, as the format's own options panel produced them.
    # The converter is the schema: each one needs a different set of flags and
    # only its panel knows which.
    options: dict[CompressionFormat, dict] = field(default_factory=dict)

    def for_format(self, fmt: CompressionFormat | None) -> dict:
        if fmt is None:
            return {}
        return dict(self.options.get(fmt, {}))
