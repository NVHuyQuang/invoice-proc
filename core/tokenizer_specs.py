"""Product specifications tokenizer / protection module.

PLAN 3.4: Preserve product specs without masking.
Strict matching against SPEC_UNITS from config.py:
Positive examples (kept as-is): 750ML, 5LB, 12OZ, A4, 500G, 6X32 OZ, 12x1 L, 12-PACK, 6-CT, 10-INCH.
Negative examples (MUST NOT be preserved as specs, MUST be masked by numbers/quantity): 2 lb, 3 ea, 1 case.
"""

import re
from functools import lru_cache
from typing import Tuple, List, Dict, Any, Optional, Set
import config


def _index_to_alpha(n: int) -> str:
    """Convert a 0-based integer index to an alphabetic string (A..Z, AA..ZZ, AAA...).

    Ensures placeholders contain no digits, protecting them from number tokenization.
    """
    result = []
    while True:
        result.append(chr(ord("A") + (n % 26)))
        n = n // 26
        if n == 0:
            break
        n -= 1
    return "".join(reversed(result))


DISALLOWED_ATTACHED_UNITS = frozenset({"EA", "CS", "CASE", "BOX"})


@lru_cache(maxsize=16)
def _compile_spec_patterns(units_tuple: Tuple[str, ...]):
    """Compile regular expressions for specification matching based on SPEC_UNITS."""
    units_sorted = sorted(units_tuple, key=len, reverse=True)
    unit_patterns = []
    for u in units_sorted:
        if u == "FL OZ":
            unit_patterns.append(r"(?:FL\s+OZ|FL-OZ|FLOZ)")
        else:
            unit_patterns.append(re.escape(u))

    unit_regex = "|".join(unit_patterns)

    # Attached format disallows counting units: EA, CS, CASE, BOX
    att_units = [u for u in units_sorted if u.upper() not in DISALLOWED_ATTACHED_UNITS]
    att_patterns = []
    for u in att_units:
        if u == "FL OZ":
            att_patterns.append(r"(?:FL\s+OZ|FL-OZ|FLOZ)")
        else:
            att_patterns.append(re.escape(u))
    att_unit_regex = "|".join(att_patterns)

    # 1. Multiplier / Division format: 6X32 OZ, 12x1 L, 24/12 OZ, 6X32OZ, 6x32-OZ, 10x12x14 INCH
    mult_re = re.compile(
        rf"(?<![A-Za-z0-9])(?P<val>\d{{1,4}}(?:\.\d{{1,3}})?(?:\s*[xX*/]\s*\d{{1,4}}(?:\.\d{{1,3}})?)+)\s*[-]?\s*(?P<unit>{unit_regex})\b",
        re.IGNORECASE
    )

    # 2. Hyphenated format: 12-PACK, 6-CT, 10-INCH (max 4 digits, tightly bound)
    hyph_re = re.compile(
        rf"(?<![A-Za-z0-9])(?P<val>\d{{1,4}}(?:\.\d{{1,3}})?)-(?P<unit>{unit_regex})\b",
        re.IGNORECASE
    )

    # 3. Attached format: 750ML, 5LB, 12OZ, 500G, 1.5L, 2.5KG, 12FLOZ, 12FL OZ
    att_re = re.compile(
        rf"(?<![A-Za-z0-9])(?P<val>\d{{1,4}}(?:\.\d{{1,3}})?)(?P<unit>FL\s+OZ|FL-OZ|FLOZ|{att_unit_regex})\b",
        re.IGNORECASE
    )

    # 4. Paper sizes: A4, A3, A5, B4, B5
    paper_re = re.compile(
        r"(?<![A-Za-z0-9])(?P<val>[Aa][0-9]|[Bb][0-9])\b"
    )

    return mult_re, hyph_re, att_re, paper_re


def _get_active_units() -> Tuple[str, ...]:
    """Retrieve current SPEC_UNITS from config as a sorted tuple for caching."""
    spec_units = getattr(config, "SPEC_UNITS", frozenset())
    return tuple(sorted(spec_units))


def protect_specs(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Identify product specification patterns and mark/protect them from number tokenization.

    Strict matching against SPEC_UNITS from config.py:
    - Attached: 750ML, 5LB, 12OZ, A4, 500G.
    - Multiplier: 6X32 OZ, 12x1 L, 24/12 OZ.
    - Hyphenated: 12-PACK, 6-CT, 10-INCH.
    - Negative examples (NOT preserved, separated quantities): 2 lb, 3 ea, 1 case.

    Args:
        text: Input string.

    Returns:
        Tuple of (protected_text, list_of_detected_specs).
    """
    if not text:
        return "" if text is not None else "", []

    units_tuple = _get_active_units()
    mult_re, hyph_re, att_re, paper_re = _compile_spec_patterns(units_tuple)

    occupied = [False] * len(text)
    raw_matches = []

    # Priority order: Multiplier -> Hyphenated -> Attached -> Paper Size
    pattern_list = [
        ("multiplier", mult_re),
        ("hyphenated", hyph_re),
        ("attached", att_re),
        ("paper_size", paper_re)
    ]

    for kind, regex in pattern_list:
        for m in regex.finditer(text):
            start, end = m.span()
            if any(occupied[start:end]):
                continue
            for i in range(start, end):
                occupied[i] = True

            unit = m.groupdict().get("unit")
            if unit:
                unit_norm = re.sub(r"[\s-]+", " ", unit.strip().upper())
            else:
                unit_norm = None

            raw_matches.append({
                "raw": m.group(0),
                "val": m.group("val"),
                "unit": unit_norm,
                "start": start,
                "end": end,
                "kind": kind
            })

    # Sort matches by start position in text ascending
    raw_matches.sort(key=lambda x: x["start"])

    # Build protected string and specs metadata
    specs: List[Dict[str, Any]] = []
    result_parts: List[str] = []
    last_idx = 0

    for idx, match in enumerate(raw_matches):
        placeholder = f"__SPEC_{_index_to_alpha(idx)}__"
        result_parts.append(text[last_idx:match["start"]])
        result_parts.append(placeholder)
        last_idx = match["end"]

        specs.append({
            "placeholder": placeholder,
            "raw": match["raw"],
            "val": match["val"],
            "unit": match["unit"],
            "start": match["start"],
            "end": match["end"],
            "kind": match["kind"]
        })

    result_parts.append(text[last_idx:])
    protected_text = "".join(result_parts)

    return protected_text, specs


def unprotect_specs(text: str, specs: List[Dict[str, Any]]) -> str:
    """Restore preserved specification text if placeholders were used during tokenization.

    Args:
        text: Tokenized text with specification placeholders.
        specs: List of preserved specifications.

    Returns:
        Final string with preserved specs restored.
    """
    if not text:
        return "" if text is not None else ""
    if not specs:
        return text

    result = text
    for spec in specs:
        ph = spec.get("placeholder")
        raw = spec.get("raw")
        if ph and raw is not None and ph in result:
            result = result.replace(ph, raw)
    return result
