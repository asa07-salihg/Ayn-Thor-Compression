# Changelog

Notable changes, newest first. Versions follow
[semantic versioning](https://semver.org/).

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
