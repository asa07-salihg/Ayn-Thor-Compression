"""Ayn Thor Compression: a desktop front end for ROM compression tools.

Every link to this project lives here, so correcting the repository address is
one edit rather than a search across the README, the issue templates, the About
box and the updater.
"""

__version__ = "1.1.0"

# The GitHub repository this build updates itself from. Nothing else in the
# code hardcodes an address for this project.
PROJECT_OWNER = "asa07-salihg"
PROJECT_NAME = "Ayn-Thor-Compression"
PROJECT_REPO = f"{PROJECT_OWNER}/{PROJECT_NAME}"

PROJECT_URL = f"https://github.com/{PROJECT_REPO}"
ISSUES_URL = f"{PROJECT_URL}/issues"
RELEASES_URL = f"{PROJECT_URL}/releases"
LATEST_RELEASE_URL = f"{RELEASES_URL}/latest"
# What the Help menu opens. The changelog rather than a docs folder: it is the
# page that answers "what changed in the build I just installed", which is what
# somebody looking for documentation on a one-window app actually wants.
CHANGELOG_URL = f"{PROJECT_URL}/blob/main/CHANGELOG.md"

# Not a GitHub address, so it is checked separately from the ones above.
# GitHub shows it as the Sponsor button from .github/FUNDING.yml as well.
SUPPORT_URL = "https://buymeacoffee.com/asa07salihg"

# The name the release workflow gives the Windows build. The updater looks for
# exactly this, and a release tracker such as Obtainium can match on it too, so
# it must not change between releases.
RELEASE_ASSET = "AynThorCompression.exe"
CHECKSUM_ASSET = "SHA256SUMS.txt"
