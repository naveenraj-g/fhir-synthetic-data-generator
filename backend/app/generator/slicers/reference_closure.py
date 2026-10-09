"""Episode extraction: cut a patient Bundle down to chosen Encounters and what belongs to them.

Observed structure of Synthea output (see plan/05): clinical resources point at their Encounter via
`encounter`, `context.encounter[]` or `item[].encounter[]`; Patient/Device/SupplyDelivery point at no
encounter; and one patient-wide `Provenance` points at ALL encounters. So:

  * a resource BELONGS to a set of encounters when every encounter it references is in that set
    (a resource referencing several encounters, like Provenance, therefore only belongs to a set that
    contains all of them);
  * resources referencing no encounter are "shared" (Patient, Device, ...): the Patient is always kept, the
    others only when an included resource references them (or a caller-supplied predicate says so);
  * Conditions referenced by included resources are pulled in (reasonReference) even if they belong to
    another encounter — one hop, not recursively;
  * any reference left pointing at something that was cut is REMOVED from the output, so the result never
    has dangling local references. References that never resolved locally (Synthea's conditional
    `Practitioner?identifier=…`, http URLs) are left alone — `attach_infrastructure` resolves those.
"""

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from app.generator import fhir

_REMOVED = object()


@dataclass
class BundleIndex:
    entries: list[dict]
    key_to_idx: dict[str, int]
    rtypes: list[str]
    refs: list[list[int]]  # per entry: indexes of entries it references (resolved locally)
    encounter_idxs: list[int]
    bindings: list[frozenset[int]]  # per entry: encounters it references (empty for shared resources)

    def resource(self, idx: int) -> dict:
        return self.entries[idx].get("resource") or {}


def build_index(bundle: dict) -> BundleIndex:
    entries = fhir.entries(bundle)
    key_to_idx: dict[str, int] = {}
    rtypes: list[str] = []
    for i, entry in enumerate(entries):
        res = entry.get("resource") or {}
        rtypes.append(fhir.resource_type(res))
        if entry.get("fullUrl"):
            key_to_idx[entry["fullUrl"]] = i
        if res.get("id"):
            key_to_idx[f"{rtypes[-1]}/{res['id']}"] = i

    refs: list[list[int]] = []
    for i, entry in enumerate(entries):
        targets = {key_to_idx[r] for r in fhir.walk_references(entry.get("resource") or {}) if r in key_to_idx}
        targets.discard(i)
        refs.append(sorted(targets))

    encounter_idxs = [i for i, t in enumerate(rtypes) if t == "Encounter"]
    enc_set = set(encounter_idxs)
    bindings = [
        frozenset() if rtypes[i] == "Encounter" else frozenset(t for t in refs[i] if t in enc_set)
        for i in range(len(entries))
    ]
    return BundleIndex(entries, key_to_idx, rtypes, refs, encounter_idxs, bindings)


def extract(
    bundle: dict,
    index: BundleIndex,
    chosen: set[int],
    *,
    keep_shared: Callable[[dict], bool] | None = None,
    related_conditions: bool = True,
) -> dict:
    """New transaction Bundle holding the chosen encounters and everything that belongs to them."""
    included: set[int] = set(chosen)
    for i, bound in enumerate(index.bindings):
        if bound and bound <= chosen:
            included.add(i)
        elif not bound and index.rtypes[i] == "Patient":
            included.add(i)
        elif not bound and index.rtypes[i] != "Encounter" and keep_shared and keep_shared(index.resource(i)):
            included.add(i)

    queue = deque(included)
    while queue:
        for target in index.refs[queue.popleft()]:
            if target in included or index.rtypes[target] == "Encounter":
                continue
            if not index.bindings[target]:  # shared resource: follow transitively
                included.add(target)
                queue.append(target)
            elif related_conditions and index.rtypes[target] == "Condition":
                included.add(target)  # one hop only: not queued

    removed = {key for key, idx in index.key_to_idx.items() if idx not in included}
    out = []
    for i in sorted(included):
        entry = dict(index.entries[i])
        entry["resource"] = prune_references(entry["resource"], removed)
        out.append(entry)
    return fhir.make_bundle(out, bundle.get("type", "transaction"))


def prune_references(node: Any, removed: set[str]) -> Any:
    """Copy of `node` without any {"reference": X} element where X is in `removed`; containers left
    empty by that are dropped too (FHIR forbids empty arrays/objects)."""
    cleaned = _prune(node, removed)
    return {} if cleaned is _REMOVED else cleaned


def _prune(node: Any, removed: set[str]) -> Any:
    if isinstance(node, dict):
        if node.get("reference") in removed:
            return _REMOVED
        out = {}
        for key, value in node.items():
            cleaned = _prune(value, removed)
            if cleaned is not _REMOVED:
                out[key] = cleaned
        if not out and node:
            return _REMOVED
        return out
    if isinstance(node, list):
        items = [c for c in (_prune(v, removed) for v in node) if c is not _REMOVED]
        return items if items or not node else _REMOVED
    return node


def attach_infrastructure(bundle: dict, infra: dict[str, dict]) -> dict:
    """Append the infrastructure resources (practitioners, organizations, locations) that the bundle's
    conditional references (`Type?identifier=system|value`) point at, so the bundle is self-contained."""
    if not infra:
        return bundle
    index = fhir.build_infra_index(infra)
    present = {(e.get("resource") or {}).get("id") for e in fhir.entries(bundle)}
    extra: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ref in sorted(fhir.reference_targets(bundle)):
        parsed = fhir.parse_conditional_reference(ref)
        if not parsed or parsed in seen or parsed not in index:
            continue
        seen.add(parsed)
        entry = index[parsed]
        if (entry.get("resource") or {}).get("id") not in present:
            extra.append(entry)
    return fhir.make_bundle(fhir.entries(bundle) + extra, bundle.get("type", "transaction"))


# ── clinical dates ───────────────────────────────────────────────────────
_DATE_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    "Encounter": (("period", "start"),),
    "Observation": (("effectiveDateTime",), ("effectivePeriod", "start"), ("issued",)),
    "Condition": (("onsetDateTime",), ("recordedDate",)),
    "Procedure": (("performedDateTime",), ("performedPeriod", "start")),
    "MedicationRequest": (("authoredOn",),),
    "MedicationAdministration": (("effectiveDateTime",), ("effectivePeriod", "start")),
    "DiagnosticReport": (("effectiveDateTime",), ("issued",)),
    "Immunization": (("occurrenceDateTime",),),
    "CarePlan": (("period", "start"),),
    "CareTeam": (("period", "start"),),
    "DocumentReference": (("date",),),
    "Claim": (("created",),),
    "ExplanationOfBenefit": (("created",),),
    "ImagingStudy": (("started",),),
    "AllergyIntolerance": (("onsetDateTime",), ("recordedDate",)),
    "SupplyDelivery": (("occurrenceDateTime",),),
    "ServiceRequest": (("authoredOn",), ("occurrenceDateTime",)),
    "Goal": (("startDate",),),
    "Media": (("createdDateTime",), ("issued",)),
    "Provenance": (("recorded",),),
}


def resource_date(resource: dict) -> str | None:
    """'YYYY-MM-DD' of the resource's clinical date, or None if it has none we know of."""
    for path in _DATE_PATHS.get(fhir.resource_type(resource), ()):
        node: Any = resource
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, str) and len(node) >= 10:
            return node[:10]
    return None


def sort_encounters(index: BundleIndex, idxs: Iterable[int]) -> list[int]:
    return sorted(idxs, key=lambda i: (resource_date(index.resource(i)) or "", i))


def filter_entries(bundle: dict, keep: Callable[[dict], bool]) -> dict:
    """New Bundle without the entries `keep` rejects. References to the dropped entries are removed from what is
    left (nothing dangles); references that never resolved locally (conditional, http) are untouched."""
    entries = fhir.entries(bundle)
    dropped = [e for e in entries if not keep(e.get("resource") or {})]
    if not dropped:
        return bundle
    removed: set[str] = set()
    for e in dropped:
        res = e.get("resource") or {}
        if e.get("fullUrl"):
            removed.add(e["fullUrl"])
        if res.get("id"):
            removed.add(f"{fhir.resource_type(res)}/{res['id']}")
    dropped_ids = {id(e) for e in dropped}
    kept = []
    for e in entries:
        if id(e) in dropped_ids:
            continue
        entry = dict(e)
        entry["resource"] = prune_references(e["resource"], removed)
        kept.append(entry)
    return fhir.make_bundle(kept, bundle.get("type", "transaction"))
