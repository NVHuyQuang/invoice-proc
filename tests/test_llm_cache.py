"""Tests for LLMCache (PLAN 4.1).

Covers:
- Cache hit and miss.
- Changing prompt_version invalidates cache (cache miss).
- Changing schema_version invalidates cache.
- Corrupted cache files are treated as cache miss without crashing the process.
- Atomic file write via temporary file.
"""

import hashlib
import json
from pathlib import Path
import pytest

from config import PROMPT_VERSION, SCHEMA_VERSION
from core.llm_cache import LLMCache, get_cache_key


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """Fixture providing an isolated temporary cache directory."""
    d = tmp_path / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def cache(cache_dir: Path) -> LLMCache:
    """Fixture providing an initialized LLMCache instance."""
    return LLMCache(cache_dir=cache_dir)


def test_get_cache_key_deterministic():
    """Verify get_cache_key produces deterministic sha256 hashes matching specification."""
    payload = "Invoice <N_1> <D_1> <ID_1>"
    prompt_ver = "2026-08-v1"
    schema_ver = "1.0"

    expected_hash = hashlib.sha256(
        f"{payload}{prompt_ver}{schema_ver}".encode("utf-8")
    ).hexdigest()

    key1 = get_cache_key(payload, prompt_ver, schema_ver)
    key2 = LLMCache.get_cache_key(payload, prompt_ver, schema_ver)

    assert key1 == expected_hash
    assert key2 == expected_hash
    assert len(key1) == 64


def test_cache_miss_on_empty(cache: LLMCache):
    """Retrieving a non-existent key returns None."""
    key = "non_existent_key_12345"
    assert cache.get(key) is None
    assert key not in cache


def test_cache_hit(cache: LLMCache):
    """Storing and retrieving valid JSON string returns the exact value."""
    payload = "Masked Invoice Item <N_1> Qty <N_2>"
    key = cache.get_cache_key(payload)
    response_data = json.dumps({"doc_type": "goods_invoice", "line_items": [{"item": "Item A"}]})

    cache.put(key, response_data)

    retrieved = cache.get(key)
    assert retrieved is not None
    assert retrieved == response_data
    assert key in cache


def test_prompt_version_change_invalidates_cache(cache: LLMCache):
    """Changing prompt_version changes the cache key, causing a cache miss."""
    payload = "Masked Invoice Item <N_1>"
    key_v1 = cache.get_cache_key(payload, prompt_version="2026-08-v1", schema_version="1.0")
    key_v2 = cache.get_cache_key(payload, prompt_version="2026-08-v2", schema_version="1.0")

    assert key_v1 != key_v2

    response_data = json.dumps({"result": "v1 response"})
    cache.put(key_v1, response_data)

    # v1 should hit
    assert cache.get(key_v1) == response_data

    # v2 should miss
    assert cache.get(key_v2) is None


def test_schema_version_change_invalidates_cache(cache: LLMCache):
    """Changing schema_version changes the cache key, causing a cache miss."""
    payload = "Masked Invoice Item <N_1>"
    key_s1 = cache.get_cache_key(payload, prompt_version="2026-08-v1", schema_version="1.0")
    key_s2 = cache.get_cache_key(payload, prompt_version="2026-08-v1", schema_version="2.0")

    assert key_s1 != key_s2

    response_data = json.dumps({"result": "schema v1 response"})
    cache.put(key_s1, response_data)

    assert cache.get(key_s1) == response_data
    assert cache.get(key_s2) is None


def test_corrupted_cache_file_treated_as_miss(cache: LLMCache, cache_dir: Path):
    """Corrupted/invalid JSON cache file must be treated as cache miss without crashing."""
    key = "corrupted_cache_key"
    cache_file = cache_dir / f"{key}.json"

    # 1. Truncated / malformed JSON
    cache_file.write_text('{"incomplete": true, "data": ', encoding="utf-8")
    assert cache.get(key) is None
    assert key not in cache

    # 2. Garbage text
    cache_file.write_text("NOT_JSON_DATA_AT_ALL!!!", encoding="utf-8")
    assert cache.get(key) is None

    # 3. Completely empty file
    cache_file.write_text("", encoding="utf-8")
    assert cache.get(key) is None

    # 4. Whitespace only
    cache_file.write_text("   \n\t  ", encoding="utf-8")
    assert cache.get(key) is None

    # 5. Invalid UTF-8 bytes
    cache_file.write_bytes(b"\x80\x81\xff\xfe")
    assert cache.get(key) is None


def test_atomic_write(cache: LLMCache, cache_dir: Path):
    """Verify put writes atomically and leaves no temporary files behind."""
    key = "atomic_key_test"
    val1 = json.dumps({"step": 1})
    val2 = json.dumps({"step": 2})

    cache.put(key, val1)
    target_path = cache_dir / f"{key}.json"
    assert target_path.is_file()
    assert cache.get(key) == val1

    # Ensure no leftover temp files
    temp_files = list(cache_dir.glob(".tmp_*"))
    assert len(temp_files) == 0

    # Overwrite with new value
    cache.put(key, val2)
    assert cache.get(key) == val2
    temp_files_after = list(cache_dir.glob(".tmp_*"))
    assert len(temp_files_after) == 0


def test_put_supports_dict_and_list(cache: LLMCache):
    """put accepts dict/list and automatically serializes to JSON string."""
    key = "dict_key"
    data = {"vendor": "ACME", "total": "<N_10>"}
    cache.put(key, data)

    cached_str = cache.get(key)
    assert cached_str is not None
    assert json.loads(cached_str) == data


def test_delete_and_clear(cache: LLMCache):
    """Verify delete and clear operations."""
    k1 = "k1"
    k2 = "k2"
    cache.put(k1, json.dumps({"k": 1}))
    cache.put(k2, json.dumps({"k": 2}))

    assert cache.get(k1) is not None
    assert cache.delete(k1) is True
    assert cache.get(k1) is None
    assert cache.delete(k1) is False

    # Clear remaining
    assert cache.get(k2) is not None
    cache.clear()
    assert cache.get(k2) is None
