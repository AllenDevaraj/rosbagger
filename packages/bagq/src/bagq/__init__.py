"""bagq: the universal "DuckDB-for-bags" SQL CLI."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bagq")
except PackageNotFoundError:  # raw source tree (not pip-installed)
    __version__ = "0.0.0+unknown"
