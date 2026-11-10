"""Run Ada with ``python -m ada``."""

from __future__ import annotations

from .cli import main


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nGoodbye.")
        raise SystemExit(0) from None
