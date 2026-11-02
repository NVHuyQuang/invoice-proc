"""CLI entrypoint for Invoice Processor.

PLAN 6.4:
Usage:
python main.py <path> [--month 2026-08] [--out output] [--only <file>] [--workers 2] [--no-cache] [--dry-run]
"""

import sys
import argparse


def main() -> int:
    """CLI execution entrypoint."""
    raise NotImplementedError("W2-cli implementation pending")


if __name__ == "__main__":
    sys.exit(main())
