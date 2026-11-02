"""Vault management module.

PLAN 3.6: Vault in-memory lifecycle, guarantees zero value leakage in repr/str/log/exceptions.
"""

from contextlib import contextmanager
from typing import Iterator, Optional
from core.types import Vault, VaultEntry


def create_vault() -> Vault:
    """Instantiate a new empty Vault for a document in RAM."""
    return Vault()


def clear_vault(vault: Optional[Vault]) -> None:
    """Completely wipe vault entries from memory.

    Safe to call with None or an already-cleared vault.
    """
    if vault is not None:
        vault.clear()


@contextmanager
def vault_scope(vault: Optional[Vault] = None) -> Iterator[Vault]:
    """Context manager for managing a Vault's lifecycle.

    Ensures that clear_vault is always called in a finally block,
    guaranteeing that raw sensitive entries are cleared from RAM
    regardless of normal completion or unhandled exceptions.

    Yields:
        Vault: The active vault instance.
    """
    v = vault if vault is not None else create_vault()
    try:
        yield v
    finally:
        clear_vault(v)


def is_vault_empty(vault: Vault) -> bool:
    """Check if the vault contains no entries."""
    return len(vault) == 0


__all__ = [
    "Vault",
    "VaultEntry",
    "create_vault",
    "clear_vault",
    "vault_scope",
    "is_vault_empty",
]
