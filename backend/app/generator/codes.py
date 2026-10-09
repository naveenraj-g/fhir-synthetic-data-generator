"""Matching FHIR CodeableConcepts against user-supplied patterns.

A pattern is either a numeric code, optionally prefixed with a code system
('44054006', 'SNOMED-CT:44054006', 'LOINC:4548'), or free text, matched case-insensitively
as a substring of the concept's display/text ('diabetes', 'appendectomy')."""

import re

from app.generator.errors import InvalidSpecError

_SYSTEM_URIS = {
    "SNOMED-CT": "http://snomed.info/sct",
    "SNOMED": "http://snomed.info/sct",
    "LOINC": "http://loinc.org",
    "RXNORM": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "ICD10": "http://hl7.org/fhir/sid/icd-10-cm",
    "ICD-10": "http://hl7.org/fhir/sid/icd-10-cm",
    "CDT": None,  # no URI known: matches by code alone
    "CVX": "http://hl7.org/fhir/sid/cvx",
}
_CODE_RE = re.compile(
    r"^(?:(?P<system>[A-Za-z][A-Za-z0-9_-]*):(?P<code>[A-Za-z0-9][A-Za-z0-9.\-]*)|(?P<bare>[0-9][0-9.\-]*))$"
)


class Pattern:
    def __init__(self, text: str):
        text = text.strip()
        if not text:
            raise InvalidSpecError("Empty code/text pattern")
        match = _CODE_RE.match(text)
        # "SYSTEM:CODE" only counts when SYSTEM is a known code system; otherwise "heart: failure" would be a code.
        known = match and (match.group("bare") or match.group("system").upper() in _SYSTEM_URIS)
        if match and known:
            self.code: str | None = match.group("bare") or match.group("code")
            system = match.group("system")
            self.system = _SYSTEM_URIS.get(system.upper()) if system else None
            self.text = None
        else:
            self.code, self.system, self.text = None, None, text.casefold()

    def matches(self, concept: dict | None) -> bool:
        if not concept:
            return False
        if self.code is not None:
            return any(
                c.get("code") == self.code and (self.system is None or c.get("system") == self.system)
                for c in concept.get("coding", [])
            )
        haystacks = [concept.get("text", "")] + [c.get("display", "") for c in concept.get("coding", [])]
        return any(self.text in h.casefold() for h in haystacks if h)


def compile_patterns(texts: list[str]) -> list[Pattern]:
    return [Pattern(t) for t in texts]


def matches_any(concept: dict | None, patterns: list[Pattern]) -> bool:
    return any(p.matches(concept) for p in patterns)
