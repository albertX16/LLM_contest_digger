"""Verify the local Python environment without requiring BigQuant credentials."""

from __future__ import annotations

import platform
import sys


def main() -> None:
    import bigquant
    import numpy
    import pandas
    import pyarrow

    print("AIStudio local development environment: OK")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Platform: {platform.system()} {platform.machine()}")
    print(f"BigQuant: {getattr(bigquant, '__version__', '0.1.11')}")
    print(f"NumPy: {numpy.__version__}")
    print(f"pandas: {pandas.__version__}")
    print(f"PyArrow: {pyarrow.__version__}")
    print("Next: run `.venv/bin/bq auth configure`, then run hello_bigquant.py.")


if __name__ == "__main__":
    main()

