"""A searchable index of the clinical terms Synthea can produce, built from the modules inside the jar.

Why: cohorts are targeted by CODE (a keep module needs codes), but callers think in words ("colonoscopy",
"gastro"). The index lets them look codes up (`GET /connectors/synthea/terms?q=colon`) instead of guessing, and
guarantees a code they pick actually exists in the pinned Synthea version.

Only states that carry codes are indexed: ConditionOnset -> condition, Procedure -> procedure,
MedicationOrder -> medication, Observation -> observation, plus allergy/immunization/device kinds."""

import json
import re
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_STATE_KINDS = {
    "ConditionOnset": "condition",
    "Procedure": "procedure",
    "MedicationOrder": "medication",
    "Observation": "observation",
    "AllergyOnset": "allergy",
    "Immunization": "immunization",
    "Device": "device",
    "DiagnosticReport": "diagnostic_report",
}
KINDS = sorted(set(_STATE_KINDS.values()))
_SYSTEM_PREFIX = {"SNOMED-CT": "SNOMED-CT", "LOINC": "LOINC", "RxNorm": "RxNorm", "CVX": "CVX", "ICD-10": "ICD10"}


def extract_terms(modules: Iterable[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """[(module_name, module_json)] -> deduplicated terms [{kind, system, code, display, modules}]."""
    found: dict[tuple[str, str, str], dict[str, Any]] = {}
    for module_name, module in modules:
        for state in (module.get("states") or {}).values():
            kind = _STATE_KINDS.get(state.get("type", ""))
            if kind is None:
                continue
            for coded in state.get("codes") or []:
                code, system = str(coded.get("code", "")), coded.get("system", "")
                if not code:
                    continue
                key = (kind, system, code)
                term = found.setdefault(
                    key,
                    {"kind": kind, "system": system, "code": code, "display": coded.get("display", ""), "modules": []},
                )
                if module_name not in term["modules"]:
                    term["modules"].append(module_name)
    return sorted(found.values(), key=lambda t: (t["kind"], t["display"].casefold(), t["code"]))


def read_modules_from_jar(jar: Path) -> list[tuple[str, dict[str, Any]]]:
    """All modules/**.json inside the Synthea jar (sub-folders hold shared sub-modules, also searched)."""
    out = []
    with zipfile.ZipFile(jar) as zf:
        for name in zf.namelist():
            if name.startswith("modules/") and name.endswith(".json"):
                try:
                    out.append((name[len("modules/") : -len(".json")], json.loads(zf.read(name))))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
    return out


def search_terms(
    terms: list[dict[str, Any]], q: str | None, kind: str | None, limit: int
) -> tuple[list[dict[str, Any]], int]:
    """Case-insensitive match on display text, code, or module name. Returns (page, total matches)."""
    needle = q.casefold().strip() if q else ""
    hits = [
        t
        for t in terms
        if (kind is None or t["kind"] == kind)
        and (
            not needle
            or needle in t["display"].casefold()
            or needle in t["code"].casefold()
            or any(needle in m.casefold() for m in t["modules"])
        )
    ]
    return hits[:limit], len(hits)


def reference_for(term: dict[str, Any]) -> str:
    """The string to put in cohort.conditions/procedures for this term, e.g. 'SNOMED-CT:44054006'."""
    system = _SYSTEM_PREFIX.get(term["system"], re.sub(r"[^A-Za-z0-9_-]", "", term["system"]) or "SNOMED-CT")
    return f"{system}:{term['code']}"
