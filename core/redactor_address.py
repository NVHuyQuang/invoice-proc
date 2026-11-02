"""Address and person name redactor module.

PLAN 3.2: Redact physical addresses and person names following key labels.
Addresses: street address (number + street name/suffix St|Ave|Blvd|Rd...), state + zip, Suite/Floor/Unit.
Person names: after Server, Cashier, Cust(omer), Guest, Member, Name on card.
Replaces matches with <ADDR> and <PERSON>.
Must NOT redact item/vendor names (e.g., "Smith's Butter", "St. Louis Ribs").
"""

from typing import Tuple, List, Dict, Any
import re

HSPACE = r"[^\S\r\n]+"

# Street suffix pattern supporting standard US street designations and abbreviations
STREET_SUFFIX = (
    r"(?:Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Way|Drive|Dr|Lane|Ln|"
    r"Court|Ct|Circle|Cir|Parkway|Pkwy|Highway|Hwy|Place|Pl|Terrace|Ter|Alley|Aly|Square|Sq)"
)

# Cardinal and intercardinal directionals
DIRECTIONAL = r"(?:N|S|E|W|NE|NW|SE|SW|North|South|East|West)"

# Unit, Suite, Floor designations that can appear at the end of a street address
SUITE_PART = (
    rf"(?:,\s*|{HSPACE})"
    r"(?:(?:Suite|Ste|Apt|Apartment|Room|Rm)\.?\s*#?\s*[A-Za-z0-9-]+"
    r"|(?:Floor|Fl)\.?\s*#?\s*\d+(?:st|nd|rd|th)?"
    r"|\d+(?:st|nd|rd|th)\s+(?:Floor|Fl)\.?"
    r"|Unit\s+#?(?!(?:Price|Cost|Rate|Total|Type|Measure|Amount|Per)\b)(?:\d+[A-Za-z]?|[A-Za-z0-9]+-[A-Za-z0-9]+|[A-Z]\b)"
    r"|#\s*[A-Za-z0-9-]+)"
)

# 50 US States + DC + PR
US_STATES = (
    r"(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|"
    r"MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC|PR)"
)

# City, State, Zip attached part
CITY_STATE_ZIP_PART = (
    rf"(?:,\s*|{HSPACE})"
    rf"(?:[A-Z][a-zA-Z.-]+(?:{HSPACE}[A-Z][a-zA-Z.-]+){{0,3}},\s*)?{US_STATES}{HSPACE}\d{{5}}(?:-\d{{4}})?"
)

# Full street address line/clause
STREET_ADDR_REGEX = re.compile(
    rf"\b\d+[\w-]*{HSPACE}"
    rf"(?:[A-Za-z0-9#.-]+{HSPACE}){{1,5}}"
    rf"{STREET_SUFFIX}\.?"
    rf"(?:{HSPACE}{DIRECTIONAL}\.?)?"
    rf"(?:{SUITE_PART})?"
    rf"(?:{CITY_STATE_ZIP_PART})?"
    rf"(?=$|[,\r\n;|]|\s{{2,}}|\s+(?=\||$|\r|\n|\d+\.\d{{2}}))",
    re.IGNORECASE,
)

# PO Box pattern
PO_BOX_REGEX = re.compile(
    rf"\b(?:P\.?\s*O\.?\s*Box|Post\s+Office\s+Box)\s+#?\s*\d+\b(?:{CITY_STATE_ZIP_PART})?",
    re.IGNORECASE,
)

# Standalone City, State, Zip or State, Zip
CITY_STATE_ZIP_STANDALONE = re.compile(
    rf"\b(?:[A-Z][a-zA-Z.-]+(?:{HSPACE}[A-Z][a-zA-Z.-]+){{0,3}},\s*)?{US_STATES}{HSPACE}\d{{5}}(?:-\d{{4}})?\b"
)

# Standalone Suite / Floor / Unit
SUITE_STANDALONE = re.compile(
    r"\b(?:"
    r"(?:Suite|Ste|Apt|Apartment|Room|Rm)\.?\s*#?\s*[A-Za-z0-9-]+"
    r"|(?:Floor|Fl)\.?\s*#?\s*\d+(?:st|nd|rd|th)?"
    r"|\d+(?:st|nd|rd|th)\s+(?:Floor|Fl)\.?"
    r"|Unit\s+#?(?!(?:Price|Cost|Rate|Total|Type|Measure|Amount|Per)\b)(?:\d+[A-Za-z]?|[A-Za-z0-9]+-[A-Za-z0-9]+|[A-Z]\b)"
    r")\b",
    re.IGNORECASE,
)

# Person labels from PLAN 3.2: Server|Cashier|Cust(omer)?|Guest|Member|Name on card
LABEL_PATTERN = (
    r"\b(?:"
    r"Server(?:\s+Name)?"
    r"|Cashier(?:\s+Name)?"
    r"|Customer(?:\s+Name)?"
    r"|Cust(?:\s+Name)?"
    r"|Guest(?:\s+Name)?"
    r"|Member(?:\s+Name)?"
    r"|Name\s+on\s+card"
    r"|Cardholder(?:\s+Name)?"
    r")\b\s*[:#-]?\s*(?:#?\d+\s+)?"
)

TERMINATORS = (
    r"(?=\s*(?:$|[\r\n,|;]|\s{2,}|\s+(?:Table|Tbl|Check|Chk|Order|Terminal|Term|Station|Date|Time|Guests?|Shift|Balance)\b))"
)

NAME_PATTERN = r"[A-Za-z][A-Za-z\'. -]*[A-Za-z.]|[A-Za-z]"

PERSON_REGEX = re.compile(
    rf"({LABEL_PATTERN})({NAME_PATTERN}){TERMINATORS}",
    re.IGNORECASE,
)

NON_PERSON_NAMES = {
    "NONE",
    "N/A",
    "NA",
    "UNKNOWN",
    "NULL",
    "WALK-IN",
    "WALKIN",
    "CASH",
    "CARD",
    "COUNT",
    "QTY",
    "GOLD",
    "SILVER",
    "PLATINUM",
    "BRONZE",
    "VIP",
    "ACTIVE",
    "INACTIVE",
    "YES",
    "NO",
    "TRUE",
    "FALSE",
}


def redact_addresses(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Redact street addresses, zip codes, and person names after staff/customer labels.

    Args:
        text: Input text (may already have contacts redacted).

    Returns:
        Tuple of (redacted_text, list_of_redaction_metadata).
    """
    if not text:
        return text, []

    candidates: List[Dict[str, Any]] = []

    # 1. Person names following specific labels
    for m in PERSON_REGEX.finditer(text):
        name_str = m.group(2).strip()
        # Must contain at least one word with 2+ letters and not be a placeholder/status keyword
        if re.search(r"[A-Za-z]{2,}", name_str) and name_str.upper() not in NON_PERSON_NAMES:
            s = m.start(2)
            e = m.end(2)
            candidates.append({
                "start": s,
                "end": e,
                "token": "<PERSON>",
                "type": "person",
                "raw": text[s:e],
            })

    # 2. Comprehensive street addresses
    for m in STREET_ADDR_REGEX.finditer(text):
        s, e = m.span()
        candidates.append({
            "start": s,
            "end": e,
            "token": "<ADDR>",
            "type": "address",
            "raw": text[s:e],
        })

    # 3. PO Box addresses
    for m in PO_BOX_REGEX.finditer(text):
        s, e = m.span()
        candidates.append({
            "start": s,
            "end": e,
            "token": "<ADDR>",
            "type": "address",
            "raw": text[s:e],
        })

    # 4. Standalone City, State, Zip or State, Zip
    for m in CITY_STATE_ZIP_STANDALONE.finditer(text):
        s, e = m.span()
        candidates.append({
            "start": s,
            "end": e,
            "token": "<ADDR>",
            "type": "address",
            "raw": text[s:e],
        })

    # 5. Standalone Suite / Floor / Unit
    for m in SUITE_STANDALONE.finditer(text):
        s, e = m.span()
        candidates.append({
            "start": s,
            "end": e,
            "token": "<ADDR>",
            "type": "address",
            "raw": text[s:e],
        })

    # Sort candidates by start position ascending, length descending
    candidates.sort(key=lambda c: (c["start"], -(c["end"] - c["start"])))

    # Filter out overlapping candidates (first-longest wins)
    accepted: List[Dict[str, Any]] = []
    last_end = -1
    for c in candidates:
        if c["start"] >= last_end:
            accepted.append(c)
            last_end = c["end"]

    # Sort accepted spans by start index
    accepted.sort(key=lambda c: c["start"])

    # Reconstruct redacted string
    result_parts: List[str] = []
    last_idx = 0
    for span in accepted:
        result_parts.append(text[last_idx:span["start"]])
        result_parts.append(span["token"])
        last_idx = span["end"]
    result_parts.append(text[last_idx:])
    redacted_text = "".join(result_parts)

    metadata: List[Dict[str, Any]] = [
        {
            "type": s["type"],
            "raw": s["raw"],
            "token": s["token"],
            "start": s["start"],
            "end": s["end"],
        }
        for s in accepted
    ]

    return redacted_text, metadata
