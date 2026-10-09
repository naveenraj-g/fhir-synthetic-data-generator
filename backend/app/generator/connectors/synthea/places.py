"""The states and cities Synthea can generate people in, read from the demographics file inside the jar.

Why: `state` and `city` are matched by exact name against that file, and a miss makes Synthea exit with
"The city worcester was not found in the demographics file for state massachusetts". Listing the valid names
lets the UI offer a picker, and lets the connector fix the capitalisation or fail early with suggestions."""

import csv
import difflib
import io
import zipfile
from pathlib import Path

from app.generator.errors import InvalidSpecError

DEMOGRAPHICS = "geography/demographics.csv"


def read_places_from_jar(jar: Path) -> dict[str, list[str]]:
    """{state name: sorted city names}. Names are exactly as Synthea spells them."""
    with zipfile.ZipFile(jar) as zf:
        raw = zf.read(DEMOGRAPHICS).decode("utf-8-sig")
    places: dict[str, set[str]] = {}
    for row in csv.DictReader(io.StringIO(raw)):
        state, city = (row.get("STNAME") or "").strip(), (row.get("NAME") or "").strip()
        if state and city:
            places.setdefault(state, set()).add(city)
    return {state: sorted(cities, key=str.casefold) for state, cities in sorted(places.items())}


def _match(value: str, options: list[str], what: str, scope: str = "") -> str:
    """The option equal to `value` ignoring case and surrounding spaces; otherwise an error with close matches."""
    wanted = value.strip().casefold()
    for option in options:
        if option.casefold() == wanted:
            return option
    close = difflib.get_close_matches(value.strip(), options, n=5, cutoff=0.6)
    raise InvalidSpecError(
        f"Unknown {what} '{value}'{scope}",
        details=[f"Did you mean: {', '.join(close)}" if close else f"List the valid {what}s with GET /connectors/synthea/places"],
    )


def resolve_place(places: dict[str, list[str]], state: str, city: str | None) -> tuple[str, str | None]:
    """Canonical (state, city) for a request, or InvalidSpecError. Case does not matter."""
    canonical_state = _match(state, list(places), "state")
    if not city or not city.strip():
        return canonical_state, None
    return canonical_state, _match(city, places[canonical_state], "city", f" in {canonical_state}")
