"""Turn MOCO offers into invoice drafts."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("moco-tui")
except PackageNotFoundError:  # running from source without install
    __version__ = "0.0.0+dev"
