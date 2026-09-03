# Changelog

Notable changes, newest first. Versions follow
[semantic versioning](https://semver.org/).

## 1.1.0

- **A file that is already compressed is added as an expand, not a compress.**
  Dropping a `.chd` in queued it as "compress to CHD", which made the output
  path the input path: depending on the conflict policy it overwrote the file or
  was silently skipped, and neither said why. `.chd`, `.rvz`, `.cso`, `.zso`,
  `.nsz`, `.xcz` and the ZCCI containers now arrive as **(decompress)** rows and
  write the original back out. Cartridge `.7z` and `.zip` files still arrive as
  archives, because that is the form RetroArch and MAME read them in; the row
  menu offers *Unzip instead of convert* for the exceptions.
- **Each direction is named after what it does.** Every reverse used to be
  called "Open", which covered unzipping an archive and decompressing a CHD and
  described neither. A row now reads `7z / ZIP (unzip)` or `CHD (decompress)`,
  and the menu entry matches.
- **The version is in the title bar**, not only in About, because that is the
  first thing a bug report asks for.
- **Help now opens the changelog** instead of a `docs/` folder.
- A support link, in the About box and as the repository's Sponsor button.
- The README screenshots are reproducible: `scripts/make_screenshots.py` builds
  them from sparse files whose sizes are the media's own capacity or a published
  figure, and every row is Waiting because nothing was converted to make them.
  The previous pair had been staged, and said "28 KB" and "saved 3.9 GB" in the
  same window.

## 1.0.0

First public release.

- Converts ROMs to the formats emulators expect: CHD, RVZ, CSO/ZSO, ZCCI/Z3DS,
  NSZ/XCZ, WUA, trimmed NDS, 7z and ZIP.
- Picks the target format from the file's platform, and lets you change it per
  row. The defaults are visible and editable under Settings > Platform presets.
- Reads a list of titles and queues the matching files off an SD card; there is
  an example in [examples/](examples/sample-list.txt).
- Installs the converters it needs on demand. Each one is pinned to a version
  and checked against a SHA-256 before it is used; see [SECURITY.md](SECURITY.md).
- Checks GitHub for a newer build of this app and can replace itself with one,
  after verifying it against the `SHA256SUMS.txt` published with the release.
  Nothing runs on a timer.
