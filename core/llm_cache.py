"""LLM response caching module.

PLAN 4.1:
- Cache key: sha256(masked_payload + PROMPT_VERSION + schema_version).
- Value: raw LLM response JSON string.
- Atomic file writes via temporary files to prevent corrupted entries on crash.
- Stored in cache/ directory (gitignored).
"""

import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional, Union

from config import PROMPT_VERSION, SCHEMA_VERSION

logger = logging.getLogger(__name__)


def get_cache_key(
    masked_payload: str,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    """Compute sha256 cache key from masked_payload + prompt_version + schema_version."""
    combined = f"{masked_payload}{prompt_version}{schema_version}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


class LLMCache:
    """Disk-backed atomic key-value cache for LLM responses."""

    def __init__(self, cache_dir: Union[Path, str] = Path("cache")) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, key: str) -> Path:
        """Return path to cache file for the given key."""
        return self.cache_dir / f"{key}.json"

    @staticmethod
    def get_cache_key(
        masked_payload: str,
        prompt_version: str = PROMPT_VERSION,
        schema_version: str = SCHEMA_VERSION,
    ) -> str:
        """Compute sha256 cache key."""
        return get_cache_key(masked_payload, prompt_version, schema_version)

    def get(self, key: str) -> Optional[str]:
        """Retrieve cached JSON string if present and valid.

        Fault-tolerant: if the cache file is missing or corrupted (invalid JSON,
        decode error, etc.), returns None without raising an exception.
        """
        path = self._get_path(key)
        if not path.is_file():
            return None
        try:
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                return None
            # Validate JSON integrity
            json.loads(content)
            return content
        except Exception as e:
            logger.warning("Cache entry for key %s is corrupted or unreadable: %s", key, e)
            return None

    def put(self, key: str, value: Union[str, dict, list, Any]) -> None:
        """Atomically store value into cache via temporary file and atomic rename."""
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        elif not isinstance(value, str):
            value = str(value)

        target_path = self._get_path(key)
        temp_path = self.cache_dir / f".tmp_{key}_{uuid.uuid4().hex}"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(value)
                f.flush()
                os.fsync(f.fileno())
            temp_path.replace(target_path)
        except Exception as e:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            logger.error("Failed to atomically write cache for key %s: %s", key, e)
            raise

    def delete(self, key: str) -> bool:
        """Delete cache entry for key. Returns True if file was deleted."""
        path = self._get_path(key)
        try:
            if path.is_file():
                path.unlink()
                return True
        except OSError as e:
            logger.warning("Failed to delete cache key %s: %s", key, e)
        return False

    def clear(self) -> None:
        """Clear all cache files in cache_dir."""
        for path in self.cache_dir.glob("*.json"):
            try:
                path.unlink()
            except OSError:
                pass

    def __contains__(self, key: str) -> bool:
        """Check if key exists in cache and is valid."""
        return self.get(key) is not None
