"""Pytest configuration and shared fixtures for Invoice Processor testing.

INVARIANTS:
1. Tests must NEVER access real invoice files.
2. Tests must NEVER make live network requests or call proxy 127.0.0.1:8045.
3. Vault contents, OCR text, and egress payloads must never be printed or logged.
"""

import sys
from pathlib import Path
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
