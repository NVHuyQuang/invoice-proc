"""Vault management module.

PLAN 3.6: Vault in-memory lifecycle, guarantees zero value leakage in repr/str/log/exceptions.
"""

from typing import Optional, Dict
from core.types import Vault, VaultEntry


def create_vault() -> Vault:
    """Instantiate a new empty Vault for a document."""
    return Vault()


def clear_vault(vault: Vault) -> None:
    """Completely wipe vault entries from memory."""
    vault.clear()
