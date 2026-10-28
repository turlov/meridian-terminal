"""PyInstaller entry point."""
import os
import sys

# Windowed builds on Windows have no console: give libraries somewhere to write.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from meridian.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
