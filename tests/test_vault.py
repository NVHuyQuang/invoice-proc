"""Tests for Vault in-memory lifecycle and privacy guarantees (PLAN 3.6).

INVARIANTS:
1. Tests NEVER access real invoice files.
2. Vault contents must NEVER be printed or logged.
3. Vault exists in RAM only.
4. repr(vault) and str(vault) never expose raw values.
5. pickle.dumps(vault) must raise TypeError.
6. Tracebacks and logs never contain raw values.
7. clear() wipes all entries from RAM.
"""

import logging
import pickle
import traceback
import pytest

from core.types import Vault, VaultEntry
from core.vault import clear_vault, create_vault, is_vault_empty, vault_scope


def _make_sample_entry(
    token: str = "<N_1>",
    raw: str = "SYNTH_9876.54",
    kind: str = "money",
    page: int = 1,
    bbox: tuple = (10.0, 20.0, 50.0, 30.0),
    conf: float = 0.98,
    neg_hint: bool = False,
) -> VaultEntry:
    """Helper to construct synthetic VaultEntry for testing (never real data)."""
    return VaultEntry(
        token=token,
        raw=raw,
        kind=kind,
        page=page,
        bbox=bbox,
        conf=conf,
        neg_hint=neg_hint,
    )


class TestVaultLifecycle:
    """Tests for Vault creation, entry addition, and memory clearance."""

    def test_create_vault_returns_empty_instance(self):
        vault = create_vault()
        assert isinstance(vault, Vault)
        assert len(vault) == 0
        assert is_vault_empty(vault)

    def test_add_and_retrieve_entries(self):
        vault = create_vault()
        entry1 = _make_sample_entry("<N_1>", "SYNTH_12.34", "money")
        entry2 = _make_sample_entry("<D_1>", "2026-08-01", "date")
        entry3 = _make_sample_entry("<ID_1>", "INV-8899", "id")

        vault.add(entry1)
        vault.add(entry2)
        vault.add(entry3)

        assert len(vault) == 3
        assert not is_vault_empty(vault)
        assert "<N_1>" in vault
        assert "<D_1>" in vault
        assert "<ID_1>" in vault
        assert "<N_999>" not in vault

        assert vault.get("<N_1>") == entry1
        assert vault["<D_1>"] == entry2
        assert vault.get("<MISSING>") is None

        with pytest.raises(KeyError):
            _ = vault["<MISSING>"]

    def test_iteration_and_dict_views(self):
        vault = create_vault()
        entries = [
            _make_sample_entry(f"<N_{i}>", f"SYNTH_{i}.00", "number")
            for i in range(1, 4)
        ]
        for e in entries:
            vault.add(e)

        tokens = list(vault)
        assert tokens == ["<N_1>", "<N_2>", "<N_3>"]
        assert list(vault.keys()) == ["<N_1>", "<N_2>", "<N_3>"]
        assert list(vault.values()) == entries
        assert list(vault.items()) == [(e.token, e) for e in entries]

    def test_clear_wipes_all_entries_from_ram(self):
        vault = create_vault()
        vault.add(_make_sample_entry("<N_1>", "SYNTH_99.99", "money"))
        vault.add(_make_sample_entry("<D_1>", "2026-01-15", "date"))
        assert len(vault) == 2

        vault.clear()

        assert len(vault) == 0
        assert is_vault_empty(vault)
        assert "<N_1>" not in vault
        assert "<D_1>" not in vault
        assert vault.get("<N_1>") is None
        assert list(vault.keys()) == []
        assert list(vault.values()) == []
        assert list(vault.items()) == []

    def test_clear_vault_helper(self):
        vault = create_vault()
        vault.add(_make_sample_entry("<N_1>", "SYNTH_50.00", "money"))
        assert len(vault) == 1

        clear_vault(vault)
        assert len(vault) == 0
        assert is_vault_empty(vault)

        # Calling clear_vault on None must be safe
        clear_vault(None)

    def test_vault_scope_normal_exit(self):
        active_vault = None
        with vault_scope() as vault:
            active_vault = vault
            vault.add(_make_sample_entry("<N_1>", "SYNTH_42.00", "money"))
            assert len(vault) == 1

        # Upon exit, entries must be wiped
        assert active_vault is not None
        assert len(active_vault) == 0
        assert is_vault_empty(active_vault)

    def test_vault_scope_exception_exit(self):
        active_vault = None
        with pytest.raises(RuntimeError, match="Simulated failure"):
            with vault_scope() as vault:
                active_vault = vault
                vault.add(_make_sample_entry("<N_1>", "SYNTH_SECRET_ERR", "money"))
                assert len(vault) == 1
                raise RuntimeError("Simulated failure")

        # Must still be wiped even after exception
        assert active_vault is not None
        assert len(active_vault) == 0
        assert is_vault_empty(active_vault)


class TestVaultInvariants:
    """Tests for zero value leakage and security invariants."""

    def test_repr_never_leaks_raw_values(self):
        vault = create_vault()
        secret_values = ["SECRET_RAW_99999", "SECRET_RAW_DATE_2026", "SECRET_TAX_ID_555"]
        vault.add(_make_sample_entry("<N_1>", secret_values[0], "money"))
        vault.add(_make_sample_entry("<D_1>", secret_values[1], "date"))
        vault.add(_make_sample_entry("<ID_1>", secret_values[2], "id"))

        repr_output = repr(vault)
        assert repr_output == "<Vault count=3 [VALUES REDACTED]>"
        for sec in secret_values:
            assert sec not in repr_output

    def test_empty_vault_repr(self):
        vault = create_vault()
        assert repr(vault) == "<Vault count=0 [VALUES REDACTED]>"

    def test_str_never_leaks_raw_values(self):
        vault = create_vault()
        secret = "SECRET_SENSITIVE_TEXT_777"
        vault.add(_make_sample_entry("<N_1>", secret, "money"))

        str_output = str(vault)
        assert str_output == "<Vault count=1 [VALUES REDACTED]>"
        assert secret not in str_output

    def test_empty_vault_str(self):
        vault = create_vault()
        assert str(vault) == "<Vault count=0 [VALUES REDACTED]>"

    def test_pickle_dumps_forbidden_raises_type_error(self):
        vault = create_vault()
        vault.add(_make_sample_entry("<N_1>", "SECRET_PICKLE_VAL", "money"))

        for proto in range(pickle.HIGHEST_PROTOCOL + 1):
            with pytest.raises(TypeError, match="Vault cannot be pickled"):
                pickle.dumps(vault, protocol=proto)

    def test_traceback_does_not_contain_raw_values_on_exception(self):
        secret = "SECRET_CRITICAL_AMOUNT_12345"
        vault = create_vault()
        vault.add(_make_sample_entry("<N_1>", secret, "money"))

        formatted_tb = ""
        try:
            # Simulate an operation failure referencing the vault
            raise ValueError(f"Processing failed for document vault: {vault}")
        except ValueError:
            formatted_tb = traceback.format_exc()

        assert "[VALUES REDACTED]" in formatted_tb
        assert secret not in formatted_tb

    def test_traceback_capture_locals_does_not_leak_raw_values(self):
        def _fail_in_worker(v: Vault):
            # In this frame, only 'v' exists in locals
            raise RuntimeError("Operation error in worker")

        secret = "SECRET_LOCAL_VAR_67890"
        vault = create_vault()
        vault.add(_make_sample_entry("<N_1>", secret, "money"))

        captured_output = ""
        try:
            _fail_in_worker(vault)
        except RuntimeError as exc:
            tb_exc = traceback.TracebackException.from_exception(exc, capture_locals=True)
            # Format only the worker frame or all frames where vault was manipulated
            worker_frame = [f for f in tb_exc.stack if f.name == "_fail_in_worker"][0]
            captured_output = str(worker_frame.locals)

        assert "[VALUES REDACTED]" in captured_output
        assert secret not in captured_output

    def test_logging_vault_does_not_leak_raw_values(self, caplog):
        secret = "SECRET_LOG_AUDIT_33333"
        vault = create_vault()
        vault.add(_make_sample_entry("<N_1>", secret, "money"))

        logger = logging.getLogger("test_vault_logger")
        with caplog.at_level(logging.DEBUG, logger="test_vault_logger"):
            logger.info("Current vault state: %s", vault)
            logger.warning("Vault repr check: %r", vault)
            try:
                raise ValueError("Vault processing issue")
            except ValueError:
                logger.exception("Error while handling vault: %s", vault)

        log_text = caplog.text
        assert "[VALUES REDACTED]" in log_text
        assert secret not in log_text

    def test_key_error_on_missing_key_does_not_leak_raw_values(self):
        secret = "SECRET_HIDDEN_VAL_4444"
        vault = create_vault()
        vault.add(_make_sample_entry("<N_1>", secret, "money"))

        missing_token = "<N_99999>"
        with pytest.raises(KeyError) as exc_info:
            _ = vault[missing_token]

        # The exception only contains the missing token name, not any stored raw value
        assert missing_token in str(exc_info.value)
        assert secret not in str(exc_info.value)
