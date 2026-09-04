# Changelog

Notable changes, newest first. Versions follow
[semantic versioning](https://semver.org/).

## 1.1.2

- **A pinned tool that moved now actually gets replaced.** The app only asked
  whether a converter's file existed, so a copy installed under an older pin sat
  in `tools/` forever, reported as installed, and no amount of bumping the
  manifest ever reached it. The files are hashed against the manifest now: the
  Tools window shows such a row as **outdated** and the button replaces it. That
  closes the loop the updater was missing, since the app updates itself from a
  GitHub release, the release carries the manifest, and the manifest is what
  decides which converter build the machine ends up running.

- **7-Zip is pinned to 26.03 and rom-converto to 0.21.0.** Both checksums were
  re-derived from the extracted files, and rom-converto 0.21.0 was checked
  against the flags this app passes it: `ctr compress` still takes a positional
  input and output with `--force`, `-l/--level` and `--allow-encrypted`, `wup
  compress` still takes `-o`, `-l` and `--key`, and `--no-update-check` is still
  there.

## 1.1.1

- **The ES-DE folder list was missing most of the disc and arcade folders.**
  Checked against ES-DE's own `es_systems.xml`: nothing it knew was wrong, but
  `arcade`, `neogeo` and the `cps` folders were unknown, and so were `saturn`,
  `segacd`, `pcenginecd`, `neogeocd`, `3do` and `pcfx`. A `.iso` in `ROMs/saturn`
  therefore fell through to the PlayStation 2 guess and picked up `createdvd`
  and hunk 2048, which are there for NetherSX2 and mean nothing to a Saturn
  core. Twelve platforms were added, along with `snesna`, `megadrivejp`,
  `mastersystem`, `gamegear`, `sega32x`, `pcengine` and `sg-1000`. A test now
  fails if the app lists a folder ES-DE does not ship, or a platform with no
  preset behind it.

- **The arcade preset was writing a ZIP into a file called `.7z`.** 7-Zip was
  told `-tzip`, which is right, but the name always came out `.7z`. FBNeo and
  MAME look for `game.zip` and never open a `.7z`, so the romset was there
  under a name those cores do not read. maxcso had the same bug: `--format=zso`
  or `dax` still produced a file called `.cso`. The name now follows the
  container the options asked for.
- **The Becomes cell names the container it will actually write.** It showed
  the format's family name, so a `.cia` said `ZCCI` while the file on disk came
  out `.zcia`, and an arcade row said `7z / ZIP` for either. It now reads
  `ZCIA`, `ZIP`, `ZSO` and so on.
- **A file already in its platform's container is skipped with a reason.** A
  `.zip` in an arcade folder had nothing to do and would have been queued to
  write over itself.

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
