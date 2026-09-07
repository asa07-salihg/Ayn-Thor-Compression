# Changelog

Notable changes, newest first. Versions follow
[semantic versioning](https://semver.org/).

## 1.3.0

- **Switch Update/DLC stay under an XCI base.** When the base is
  `Game.xci/Game.xci`, same-game `.nsp` updates and DLC no longer invent a
  sibling `Game.nsp/` folder; they write into the base tree.
- **RAR/7z members with `[title id]` extract correctly.** 7-Zip treated
  `[0100…]` as a wildcard and unpacked nothing; Move now selects by title id
  (or falls back to a full extract) so Switch update RARs no longer fail after
  unpacking.
- **In-place game folders work on Windows.** Folding `Game.chd` into
  `Game.chd/Game.chd` no longer fails with "Cannot create a file when that
  file already exists"; the file is moved aside, the folder is created, then
  the ROM is moved in.
- **Rename updates the primary ROM too.** Renaming a game folder also
  renames `Old.nsp/Old.nsp` to `New.nsp/New.nsp`, so ES-DE can still launch it.
- **Queue sizes use the ROM, not the archive.** A peeked zip/rar row shows
  (and saves against) the member's size, not the whole archive's. On-disk
  seed rows count toward the footer total.
- **Settings stays on screen.** The dialog is capped to the available
  desktop area; tall pages scroll inside instead of growing past the display.
- **Game-folder Becomes is multi-select.** Click Becomes (or Platform) on a
  tree folder to change every child; several selected folders apply together.
  Choosing Move also renames the folder from `.nsz` to `.nsp` so the label
  matches what will actually be written.
- **Large Moves no longer sit on 99%.** After a RAR/zip unpack finishes, the
  copy into the game folder reports its own progress instead of freezing the
  bar until a silent 14 GB copy ends.
- **Move from zip/rar writes once.** The member goes straight into the game
  folder — no sibling `.aynthor-unpack-*` full of a second copy.
- **Each game can go in a folder named like its primary file.** Settings >
  General has "Put each game in its own folder", which writes
  `psx/Final Fantasy VIII.chd/Final Fantasy VIII.chd` (extra discs, updates and
  DLC sit beside it). That is how ES-DE and Cocoon find a title when they
  search subfolders. The older Switch-only grouping is this, for every
  platform; anyone who had that on keeps it.
- **A zip that holds a ROM is opened, not re-archived.** Adding `Game.zip`
  that contains `Game.iso` used to queue "compress to 7z", which nested an ISO
  inside a zip inside a 7z. The zip is listed first, the ROM inside decides
  the format, and at run time the archive is unpacked, converted, then
  discarded. Arcade romsets are left alone.
- **Adding a folder shows the folder in the queue.** The File column reads
  `psx/Game.chd/Game.cue` rather than a bare filename, so you can see where
  each row came from. Files added one at a time still show only their name.
- **The queue is a tree of game folders.** Base, update, DLC and extra discs
  sit under a folder named like the primary ROM (`Game.chd/Game.chd`). A file
  the app could not group can be dragged onto that folder; the primary file is
  always renamed to match the folder exactly. Empty `Game.chd/` directories
  show up as drop targets when Settings > General > "Show empty folders in
  the queue" is on (off by default) and sit at the bottom of each tree
  level so filled titles stay in view.
- **Adding a folder shows the directory tree, even with no ROMs.** An ES-DE
  `ROMs/` folder full of empty `psx/`, `snes/` and friends now appears in
  the queue as drop targets. The Platform cell lists every ES-DE folder
  (grouped by family), not only the formats that match the current file.
- **A zip of several discs is one game.** Four ISOs or cue sheets in one
  archive become four rows under one folder, the archive is unpacked once
  for the whole set, and the zip is not deleted until every disc has
  finished. A cue sheet wins over an ISO of the same disc.
- **A zip in a cartridge folder is no longer treated as an arcade romset.**
  `snes/Mario.zip` follows the SNES preset (becomes 7z) instead of being
  skipped as "already a zip". Arcade folders (`fbneo`, `mame`, `arcade`)
  still leave romsets alone.
- **Add files shows zip archives.** The Windows picker was given every
  extension in one long filter; it truncated the list from the end, so
  `.7z` still appeared and `.zip` did not. ZIP, 7z and RAR are now the
  first (short) filter group.
- **A RAR is opened like a zip.** Switch dumps that arrive as `.rar` are
  listed with full 7-Zip (`7z.exe`; `7za` cannot read RAR), the ROM
  inside is queued (an NSP becomes NSZ), and the archive is unpacked at
  run time. The ROM inside can be any recognised dump, not only NSP.
- **RAR/ZIP members unpack even when folder names disagree.** After peek, the
  row is the ROM inside — use Move or convert to NSZ, not a separate Unzip.
  Extraction finds the file by exact path, basename, or fuzzy name (spaces vs
  underscores) when 7-Zip’s listing and the folder Windows wrote differ.
- **Join files to a game folder already on the card.** When a destination
  ROMs folder is set and a matching game folder exists, adding a file asks
  whether to put it there. The queue shows files already on the card as
  “Already on card” (not converted). Drag one game tree onto another to
  merge (target name kept). Right-click a game folder → Rename edits the
  stem and renames the folder on disk too. Matching is by title header
  across every platform; not by words like dlc/update.
- **Switch: one base title, one tree.** After a base is known, every file
  whose name starts with that title joins the same folder. Underscores are
  read as spaces so `pack_dlc` is detected as DLC, not Base.

- **Larger type and expand/collapse.** Queue text is a step bigger, and
  Expand all / Collapse all sit on the drop strip once there is a tree.

## 1.2.1

- **Decrypting a CIA failed with "Unsupported CIA type", every time.** The
  crypto key was read from ctrtool's output with a pattern that expected a
  colon, and the ctrtool this app ships prints the line without one. The key
  therefore always came back empty: a CIA could never be recognised as
  encrypted, and a `.3ds` that was already decrypted was quietly repacked
  by makerom instead of being refused. Both read the key now, and a test
  runs each path against the tool's real output.

## 1.2.0

### Security

A pass over every trust boundary in the app: what crosses it, and what checks it.

- **An imported list could choose where the converter wrote.** The Switch
  grouping folder is the game name, and for an imported list that name is a
  line from a text file somebody handed the user. `../../../Startup` walked out
  of the output folder, and on Windows `C:/Windows/Temp` replaced it outright,
  because joining an absolute path discards everything to its left. The name is
  reduced to one folder component now.
- **The app left a permanent copy of your `prod.keys`.** nsz reads its keys
  from its working directory, so the file was copied to the app's data folder
  as `keys.txt` and never removed. It exists for the length of one conversion
  now and is deleted afterwards, including when the conversion fails.
- **The 7z extractor fell back to whatever was first on `PATH`.** That is an
  unverified executable, run to unpack the archives every other tool arrives
  in. Only the verified copy runs; a test fails if `shutil.which` reappears.
- **A ROM named like an option was one.** The converters take files as
  positional arguments and none supports `--`, so a file called `-o` reached
  chdman's command line as a flag. Every path is absolute before it gets there.
- **A file could expand until the disk filled.** The Z3DS decoder wrote until
  the input ran out and compared the size afterwards; a four-byte field could
  also ask for a four gigabyte allocation. Both are bounded by what the
  container itself declares.
- **The conflict policy was skipped whenever a converter re-derived the output
  name.** Opening a generic `.z3ds` took its extension from the header, and the
  CIA to CCI step wrote a path nobody had checked, so `Skip` could still
  destroy an existing file. Both refuse instead.
- **The 3DS tools were staged by file size.** They are copied to a fixed,
  user-writable folder and run from there, so anything of the right length sat
  in it forever and no amount of verifying `tools/` noticed. Compared by
  content now.
- **Delete-source proved an output existed, not that this run wrote it.** With
  overwrite selected a leftover from an earlier run satisfied every guard.
- **Archives are bounded before extraction**, which happens before the archive
  has been hashed, and the updater refuses a checksum that is not 64 hex
  characters, an asset listed twice with different hashes, and an install path
  a batch file cannot carry.

### Other

- **Output path rules moved into `core`.** They decide where a converted file
  lands and they touch no Qt, but they lived in the queue widget, so the tests
  for them had to import a widget module and the engine suite, which CI runs
  with PySide6 not installed, could not load them. A test now fails if any file
  outside the interface suite imports Qt or `aynthor.ui` at all.

## 1.1.3

- **The output can go straight into an ES-DE ROMs folder.** Set it under
  Settings > General and a converted file is written into the platform
  folder it belongs in, rather than beside its input. That is what someone
  converting a fresh download wants: the file lands where the emulator looks
  for it instead of in a pile to be sorted afterwards.
- **The queue has a Platform column**, left of Becomes and clickable the same
  way. A file in a card's `ps2` folder fills it in by itself; a download sitting
  in `Downloads` has nothing to go on, so this is where you say what it is.
  Picking a platform also applies that platform's format and flags to the row.
- **Changing a row's format no longer carries the old format's settings.**
  `level` means 5 to DolphinTool and 9 to 7-Zip, so a GameCube row switched to
  7z was archiving at level 5 and saying nothing. A format change now reloads
  that format's own settings and keeps only the row's game grouping. A test
  fails if another option key ever ends up shared between two formats.
- **`audit_folders` returned a dictionary its own type annotation described
  wrongly**, holding two mappings and a string together. It returns a small
  record now, which is what the reader and the type checker both needed.
- **The ES-DE folder is resolved once, not once per file.** Working out whether
  the chosen folder was the ROMs folder or the one above it reads the disk, and
  the queue asked per row; a two thousand file card asked two thousand times.
- **The bundled copy of a tool no longer overwrites one you just updated.**
  The frozen build unpacks its tools next to the exe and compared them by size,
  so pressing *Update outdated* fixed a tool and the next launch put the old one
  back, leaving the row outdated forever. It only fills a gap now; replacing a
  tool is the Tools window's job, and that checks hashes.

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
