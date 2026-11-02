"""Core data types and contracts for Invoice Processor.

Frozen at Wave 0. Any modifications require Orchestrator sign-off and contract tag increment.
"""

from dataclasses import dataclass, field
from typing import Iterator, Optional, Tuple, Dict, Any


@dataclass(frozen=True)
class Provenance:
    """Tracks origin of a extracted value."""
    page: int
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
    ocr_conf: float
    source: str  # "pdf_text" | "ocr"


@dataclass(frozen=True)
class Word:
    """Normalized text token from PDF text layer or OCR engine."""
    text: str
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
    conf: float  # 0.0 to 1.0 (1.0 for pdf_text)
    page: int  # 1-indexed
    source: str  # "pdf_text" | "ocr"


@dataclass
class Line:
    """A reconstructed horizontal line of words/cells."""
    page: int
    y: float
    cells: list[Tuple[str, Tuple[float, float, float, float], float, int]] = field(default_factory=list)
    # Each cell: (text, bbox, conf, col_idx)


@dataclass
class Page:
    """A single page within a document."""
    page_num: int  # 1-indexed
    width: float
    height: float
    words: list[Word] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)


@dataclass
class Document:
    """A full multi-page document."""
    file_path: str
    sha256: str
    pages: list[Page] = field(default_factory=list)

    @property
    def all_words(self) -> list[Word]:
        words = []
        for p in self.pages:
            words.extend(p.words)
        return words


@dataclass(frozen=True)
class VaultEntry:
    """An entry in the in-memory Vault storing true raw values."""
    token: str  # e.g. "<N_1>", "<D_1>", "<ID_1>"
    raw: str  # Raw string e.g. "$12.50", "08/01/2026"
    kind: str  # "number" | "date" | "id" | "money"
    page: int
    bbox: Tuple[float, float, float, float]
    conf: float
    neg_hint: bool = False  # True if bracketed, trailing minus, CR

    def __repr__(self) -> str:
        return (
            f"VaultEntry(token={self.token!r}, raw='[REDACTED]', kind={self.kind!r}, "
            f"page={self.page!r}, bbox={self.bbox!r}, conf={self.conf!r}, neg_hint={self.neg_hint!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()



class Vault:
    """In-memory secure store for masked numbers, dates, and identifiers.

    INVARIANTS:
    1. Exists in RAM only.
    2. __repr__ and __str__ never output raw values.
    3. Pickle is forbidden.
    4. Must be cleared via clear() in finally block after processing.
    """

    def __init__(self) -> None:
        self._entries: Dict[str, VaultEntry] = {}

    def add(self, entry: VaultEntry) -> None:
        self._entries[entry.token] = entry

    def get(self, token: str) -> Optional[VaultEntry]:
        return self._entries.get(token)

    def __getitem__(self, token: str) -> VaultEntry:
        return self._entries[token]

    def __contains__(self, token: str) -> bool:
        return token in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def keys(self):
        return self._entries.keys()

    def values(self):
        # Prevent exposing raw entry list directly in repr/iter leaks
        return self._entries.values()

    def items(self):
        return self._entries.items()

    def clear(self) -> None:
        """Wipe all vault contents from memory."""
        self._entries.clear()

    def __repr__(self) -> str:
        return f"<Vault count={len(self._entries)} [VALUES REDACTED]>"

    def __str__(self) -> str:
        return f"<Vault count={len(self._entries)} [VALUES REDACTED]>"

    def __reduce__(self):
        raise TypeError("Vault cannot be pickled or serialized to preserve financial privacy")
