"""Canonical parts catalogue: normalised lookup + manufacturer alias resolution.

Deliberately plain string matching, not embeddings. The catalogue is 29 rows and
the failure mode that matters is a *wrong confident* match, not a missed fuzzy one.
Anything below an exact or clean family match is reported as ambiguous and left to
a human rather than guessed at.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache

from .config import CATALOG_PATH

_NORM_RE = re.compile(r"[^A-Z0-9]")

# Buyers write shorthand as readily as full names. Resolving these is the
# "normalisation" part of the spec's Option C.
MANUFACTURER_ALIASES = {
    "TI": "Texas Instruments",
    "TEXASINSTRUMENTS": "Texas Instruments",
    "ONSEMI": "ON Semiconductor",
    "ONSEMICONDUCTOR": "ON Semiconductor",
    "ON": "ON Semiconductor",
    "ST": "STMicroelectronics",
    "STMICRO": "STMicroelectronics",
    "STMICROELECTRONICS": "STMicroelectronics",
    "MICROCHIP": "Microchip Technology",
    "ATMEL": "Microchip Technology",
    "INFINEON": "Infineon Technologies",
    "IR": "Infineon Technologies",
    "INTERNATIONALRECTIFIER": "Infineon Technologies",
    "VISHAY": "Vishay",
    "MAXIM": "Maxim Integrated",
    "MAXIMINTEGRATED": "Maxim Integrated",
    "DIODES": "Diodes Incorporated",
    "DIODESINCORPORATED": "Diodes Incorporated",
    "WINBOND": "Winbond",
    "FTDI": "FTDI",
    "YAGEO": "Yageo",
    "MURATA": "Murata",
    "UBLOX": "u-blox",
    "ILITEK": "Ilitek",
    "AMS": "Advanced Monolithic Systems",
}


@dataclass(frozen=True)
class CatalogEntry:
    mpn: str
    manufacturer: str
    description: str


@dataclass
class Match:
    """One lookup outcome. `status` drives what the agent is allowed to do with it."""

    query: str
    status: str  # "exact" | "ambiguous" | "not_found"
    entries: list[CatalogEntry]

    def as_tool_payload(self) -> dict:
        return {
            "query": self.query,
            "status": self.status,
            "matches": [
                {"mpn": e.mpn, "manufacturer": e.manufacturer, "description": e.description}
                for e in self.entries
            ],
        }


def normalize(value: str) -> str:
    return _NORM_RE.sub("", (value or "").upper())


def canonical_manufacturer(value: str | None) -> str | None:
    """Resolve 'TI' / 'ON Semi' / 'ST' to the catalogue's canonical spelling."""
    if not value:
        return None
    return MANUFACTURER_ALIASES.get(normalize(value), value.strip())


@lru_cache(maxsize=1)
def load_catalog() -> tuple[CatalogEntry, ...]:
    if not CATALOG_PATH.exists():
        return ()
    with CATALOG_PATH.open(newline="", encoding="utf-8") as fh:
        return tuple(
            CatalogEntry(
                mpn=row["mpn"].strip(),
                manufacturer=row["manufacturer"].strip(),
                description=row["description"].strip(),
            )
            for row in csv.DictReader(fh)
            if row.get("mpn")
        )


def lookup(query: str) -> Match:
    entries = load_catalog()
    q = normalize(query)
    if not q:
        return Match(query=query, status="not_found", entries=[])

    exact = [e for e in entries if normalize(e.mpn) == q]
    if len(exact) == 1:
        return Match(query=query, status="exact", entries=exact)
    if len(exact) > 1:
        return Match(query=query, status="ambiguous", entries=exact)

    # Family match: "LM358" -> LM358N / LM358D / LM358AN. One hit is good enough
    # to canonicalise; several means the package/grade suffix was never specified.
    family = [e for e in entries if normalize(e.mpn).startswith(q)]
    if len(family) == 1:
        return Match(query=query, status="exact", entries=family)
    if len(family) > 1:
        return Match(query=query, status="ambiguous", entries=family)

    # Last resort: the query contains a catalogue part ("USB-C 16-pin connector"
    # style free text). Substring only, never the other direction.
    contained = [e for e in entries if normalize(e.mpn) and normalize(e.mpn) in q]
    if len(contained) == 1:
        return Match(query=query, status="exact", entries=contained)
    if len(contained) > 1:
        return Match(query=query, status="ambiguous", entries=contained)

    return Match(query=query, status="not_found", entries=[])


def lookup_many(queries: list[str]) -> list[Match]:
    return [lookup(q) for q in queries]
