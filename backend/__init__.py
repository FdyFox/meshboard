"""Meshboard – Backend."""
import os

__version__ = "0.1.0"  # bei einem Release gleich dem Tag v<Version> und einem Abschnitt in CHANGELOG.md
# Images aus der CI tragen ihre genaue Version (z. B. 0.1.0-test.abc1234) als Umgebungsvariable
VERSION = os.environ.get("MESHBOARD_VERSION") or __version__
