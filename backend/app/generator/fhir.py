"""Small helpers over FHIR Bundles represented as plain dicts. Plain dicts (not
fhir.resources models) on purpose: fast on large cohorts and tolerant of
profile extensions — see plan/02-architecture.md."""

from collections.abc import Iterable, Iterator
from typing import Any


def resource_type(resource: dict) -> str:
    return resource.get("resourceType", "")


def entries(bundle: dict) -> list[dict]:
    return bundle.get("entry", [])


def resources(bundle: dict) -> Iterator[dict]:
    for entry in entries(bundle):
        res = entry.get("resource")
        if res:
            yield res


def make_bundle(entry_list: list[dict], bundle_type: str = "transaction") -> dict:
    return {"resourceType": "Bundle", "type": bundle_type, "entry": entry_list}


def walk_references(node: Any) -> Iterator[str]:
    """Yield every `reference` string anywhere inside a resource."""
    if isinstance(node, dict):
        ref = node.get("reference")
        if isinstance(ref, str):
            yield ref
        for value in node.values():
            yield from walk_references(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_references(item)


def build_infra_index(infra: dict[str, dict]) -> dict[tuple[str, str], dict]:
    """Index infrastructure resources (practitioners, hospitals…) by (type, 'system|value')
    for each identifier, so Synthea's conditional references
    (`Practitioner?identifier=system|value`) can be resolved."""
    index: dict[tuple[str, str], dict] = {}
    for bundle in infra.values():
        for entry in entries(bundle):
            res = entry.get("resource") or {}
            for ident in res.get("identifier", []):
                key = (resource_type(res), f"{ident.get('system', '')}|{ident.get('value', '')}")
                index[key] = entry
    return index


def parse_conditional_reference(ref: str) -> tuple[str, str] | None:
    """'Practitioner?identifier=sys|val' -> ('Practitioner', 'sys|val'); None for other reference styles."""
    if "?identifier=" not in ref:
        return None
    rtype, _, rest = ref.partition("?identifier=")
    return rtype, rest


def reference_targets(bundle: dict) -> set[str]:
    """Every reference the bundle's resources make."""
    refs: set[str] = set()
    for res in resources(bundle):
        refs.update(walk_references(res))
    return refs


def local_keys(bundle: dict) -> set[str]:
    """Every string a reference could use to point at an entry in this bundle."""
    keys: set[str] = set()
    for entry in entries(bundle):
        if entry.get("fullUrl"):
            keys.add(entry["fullUrl"])
        res = entry.get("resource") or {}
        if res.get("id"):
            keys.add(f"{resource_type(res)}/{res['id']}")
        for ident in res.get("identifier", []):
            keys.add(
                f"{resource_type(res)}?identifier={ident.get('system', '')}|{ident.get('value', '')}"
            )
    return keys


def dangling_references(bundle: dict) -> list[str]:
    """References that do not resolve inside the bundle. Ignored on purpose: absolute http(s) URLs
    (external) and '#id' fragments, which point at a `contained` resource inside the same resource
    (Synthea uses these, e.g. '#coverage')."""
    keys = local_keys(bundle)
    return sorted(
        r
        for r in reference_targets(bundle)
        if r not in keys and not r.startswith(("http://", "https://", "#"))
    )


class StageCounter:
    """Counts what flows out of one pipeline stage (the connector, or one slicer) as the next stage pulls from it,
    so the job can show how many bundles and resources each step kept. Lazy like the stream it wraps."""

    def __init__(self, bundles: Iterable[dict]):
        self._bundles = bundles
        self.bundles = 0
        self.by_type: dict[str, int] = {}

    def __iter__(self) -> Iterator[dict]:
        for bundle in self._bundles:
            self.bundles += 1
            for res in resources(bundle):
                rt = resource_type(res)
                self.by_type[rt] = self.by_type.get(rt, 0) + 1
            yield bundle

    def summary(self) -> dict:
        return {"bundles": self.bundles, "resources": sum(self.by_type.values()), "by_type": dict(sorted(self.by_type.items()))}


class StatsCollector:
    """Wraps a bundle iterator and tallies patients/resources as the consumer pulls
    from it, so sinks can stream without the pipeline materialising everything."""

    def __init__(self, bundles: Iterable[dict]):
        self._bundles = bundles
        self.bundle_count = 0
        self.by_type: dict[str, int] = {}
        self.dangling: set[str] = set()
        self.check_references = False

    def __iter__(self) -> Iterator[dict]:
        for bundle in self._bundles:
            self.bundle_count += 1
            for res in resources(bundle):
                rt = resource_type(res)
                self.by_type[rt] = self.by_type.get(rt, 0) + 1
            if self.check_references:
                self.dangling.update(dangling_references(bundle))
            yield bundle

    def summary(self) -> dict:
        return {
            "bundles": self.bundle_count,
            "patients": self.by_type.get("Patient", 0),
            "resources": dict(sorted(self.by_type.items())),
            "total_resources": sum(self.by_type.values()),
        }
