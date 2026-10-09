from app.generator import registry
from app.generator.resource_groups import GROUPS
from app.generator.runtime import GeneratorRuntime
from app.schemas.generation import (
    ComponentInfo,
    ConnectorHealthResponse,
    ConnectorInfo,
    PlacesResponse,
    PresetInfo,
    TermSearchResponse,
)


class CatalogService:
    """Read-only discovery: what connectors, slicers, sinks, specialties and presets
    exist. Drives API consumers today and a spec-builder UI later."""

    def __init__(self, runtime: GeneratorRuntime):
        self.runtime = runtime

    def connectors(self) -> list[ConnectorInfo]:
        out = []
        for name, entry in self.runtime.config.connectors.items():
            enabled = entry.get("enabled", True)
            info = ConnectorInfo(name=name, type=entry["type"], enabled=enabled)
            if enabled:
                caps = self.runtime.get_connector(name).capabilities()
                info.native_filters = sorted(caps.native_filters)
                info.fhir_versions = sorted(caps.fhir_versions)
                info.deterministic = caps.deterministic
            out.append(info)
        return out

    async def connector_health(self, name: str) -> ConnectorHealthResponse:
        health = await self.runtime.get_connector(name).healthcheck()
        return ConnectorHealthResponse(name=name, ok=health.ok, detail=health.detail)

    async def search_terms(self, name: str, q: str | None, kind: str | None, limit: int) -> TermSearchResponse:
        items, total = await self.runtime.get_connector(name).terms(q, kind, limit)
        return TermSearchResponse(total=total, returned=len(items), items=items)

    async def places(self, name: str, state: str | None) -> PlacesResponse:
        items = await self.runtime.get_connector(name).places(state)
        return PlacesResponse(state=state, items=items)

    @staticmethod
    def resource_groups() -> dict[str, list[str]]:
        return {name: list(types) for name, types in GROUPS.items()}

    def slicers(self) -> list[ComponentInfo]:
        return [
            ComponentInfo(
                name=name,
                description=cls.description,
                params_schema=cls.Params.model_json_schema(),
            )
            for name in registry.slicers.names()
            for cls in [registry.slicers.get(name)]
        ]

    def sinks(self) -> list[ComponentInfo]:
        out = []
        for name, entry in self.runtime.config.sinks.items():
            if entry.get("enabled", True) is False:
                continue
            cls = registry.sinks.get(entry["type"])
            out.append(
                ComponentInfo(
                    name=name,
                    description=cls.description,
                    params_schema=cls.Options.model_json_schema(),
                )
            )
        return out

    def specialties(self) -> dict[str, dict]:
        return self.runtime.config.specialties

    def presets(self) -> list[PresetInfo]:
        # Config order, so a category's templates stay together in the order they were written.
        return [self._preset_info(name) for name in self.runtime.config.presets]

    def preset(self, name: str) -> PresetInfo:
        self.runtime.config.preset(name)  # raises InvalidSpecError if unknown
        return self._preset_info(name)

    def _preset_info(self, name: str) -> PresetInfo:
        p = self.runtime.config.presets[name]
        return PresetInfo(
            name=name,
            title=p.title,
            category=p.category,
            description=p.description,
            connector=p.connector,
            cohort=p.cohort,
            shape=[s.model_dump() for s in p.shape] if p.shape is not None else None,
            sink=p.sink.model_dump() if p.sink else None,
        )
