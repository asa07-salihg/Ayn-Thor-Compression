# Security

## Reporting a vulnerability

Open a [private security advisory](https://github.com/asa07-salihg/Ayn-Thor-Compression/security/advisories/new).
Please do not use a public issue for anything that lets someone run code on
another user's machine.

## The part worth scrutinising

This app downloads executables and runs them. That is what it is for, and it is
where the risk lives.

**Downloads go through one path.** The tool installer and the updater both use
[`core/net.py`](src/aynthor/core/net.py) and nothing else, so both get the same
rules: HTTPS only including after a redirect (release assets redirect to a CDN,
so redirects must be followed, but one that drops to plain HTTP is refused),
certificates and hostnames verified explicitly, a size cap and a timeout on
every request, and a partial download deleted rather than left behind.

**Downloads are verified.** Every file is fetched to a scratch directory,
unpacked there, hashed, and copied into `tools/` only once its SHA-256 matches
the value recorded in
[`core/tools/manifest.py`](src/aynthor/core/tools/manifest.py). Versions are
pinned, so a moved or replaced upstream release cannot change what lands on
disk. Only the archive members the manifest names are extracted, and an entry
that would write outside the target directory is refused before extraction and
checked again after.

**One download cannot be verified.** Dolphin publishes its Windows builds from
its own server with no signature and no digest, so there is nothing to pin
against. That entry carries `sha256=None`, the Tools window marks it
**unverified**, and the app offers to copy `DolphinTool.exe` out of a Dolphin
install you already trust instead. It is the only such entry, and a test fails
if another appears.

**An installed tool is re-checked, not trusted because it is there.** Its files
are hashed against the manifest, so a copy left over from an older pin is shown
as outdated and replaced with the pinned build rather than being used forever.

**Checking for newer tools never installs one.** A version that is not in the
manifest has no checksum to be verified against, so an updated tool ships in the
next release of this app instead, after someone has read the upstream changelog
for flag changes.

**Updating the app itself** happens only on a button press. The new executable
is verified against the `SHA256SUMS.txt` published with the same release; a
mismatch discards the download and reports both digests, and a release with no
checksum file cannot be installed from inside the app at all.

## Console keys

**This project never ships, downloads, transmits or logs `prod.keys`.**

Switch compression needs keys dumped from a console you own. The app looks for
them next to the exe, in `%USERPROFILE%\.switch\prod.keys`, or at a path you
select, and the only thing it does with the file is copy it, on your machine,
into the working directory nsz reads from.

`prod.keys`, `keys.txt` and `*.keys` are in `.gitignore`. Do not remove them: a
keys file in a public repository is a takedown risk for the whole project, and
git history keeps it after the file is deleted.

## What the app sends

HTTPS GETs to the release URLs in the manifest when you install a tool,
`pip install nsz` when you install that one, and one GitHub API request when you
press Check for updates. No telemetry, no background checks, no crash reporting.

## The released exe

Built by GitHub Actions from the tagged source
([`release.yml`](.github/workflows/release.yml)), with a `SHA256SUMS.txt` beside
it:

```powershell
Get-FileHash .\AynThorCompression.exe -Algorithm SHA256
```

It is not code-signed, so SmartScreen warns on first run. Verify the hash, or
build it yourself.

## Your files

Everything happens locally; nothing is uploaded. Two operations modify files in
place. **NDS trim** rewrites the cart image, copying it first when the output
path differs from the input. **Delete the source file** removes the input after
a successful conversion: it is off by default, never remembered between
sessions, asks for confirmation before a batch, and refuses unless the converter
reported success and the output exists, differs from the input and is not empty.
