"""LLM response caching module.

PLAN 4.1:
- Cache key: sha256(masked_payload + PROMPT_VERSION + schema_version).
- Value: raw LLM response JSON string.
- Atomic file writes via temporary files to prevent corrupted entries on crash.
- Stored in cache/ directory (gitignored).
"""

from pathlib import Path
from typing import Optional


class LLMCache:
    """Disk-backed atomic key-value cache for LLM responses."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cache_key(self, masked_payload: str, prompt_version: str, schema_version: str) -> str:
        """Compute sha256 cache key."""
        raise NotImplementedError("W1-llm-cache implementation pending")

    def get(self, key: str) -> Optional[str]:
        """Retrieve cached JSON string if present and valid."""
        raise NotImplementedError("W1-llm-cache implementation pending")

    def put(self, key: str, value: str) -> None:
        """Atomically store value into cache."""
        raise NotImplementedError("W1-llm-cache implementation pending")
