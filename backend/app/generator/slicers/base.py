from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError

from app.generator.errors import InvalidSpecError


@dataclass
class SliceContext:
    """Read-only extras a slicer may need besides the bundles themselves."""

    infra: dict[str, dict] = field(default_factory=dict)  # hospital/practitioner bundles
    meta: dict[str, Any] = field(default_factory=dict)


class SlicerParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Slicer(ABC):
    """Pure transformation over FHIR Bundles. Knows nothing about how they were generated
    or where they go."""

    name: ClassVar[str]
    description: ClassVar[str] = ""
    Params: ClassVar[type[SlicerParams]] = SlicerParams

    def __init__(self, params: dict[str, Any]):
        try:
            self.params = self.Params(**params)
        except ValidationError as exc:
            raise InvalidSpecError(
                f"Invalid params for slicer '{self.name}'",
                details=[
                    {"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()
                ],
            ) from None

    @abstractmethod
    def apply(self, bundles: Iterable[dict], ctx: SliceContext) -> Iterator[dict]: ...
