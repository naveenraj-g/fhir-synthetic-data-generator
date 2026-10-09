from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError

from app.generator.errors import InvalidSpecError


@dataclass
class ArtifactFile:
    filename: str
    path: Path
    content_type: str
    size: int


@dataclass
class DeliveryResult:
    artifacts: list[ArtifactFile] = field(default_factory=list)
    inline: list[dict] | None = None  # bundles returned directly in the response


@dataclass
class DeliveryContext:
    artifact_dir: Path
    inline_max_bytes: int


class SinkOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Sink(ABC):
    name: ClassVar[str]
    description: ClassVar[str] = ""
    Options: ClassVar[type[SinkOptions]] = SinkOptions
    returns_inline: ClassVar[bool] = False

    def __init__(self, options: dict[str, Any]):
        try:
            self.options = self.Options(**options)
        except ValidationError as exc:
            raise InvalidSpecError(
                f"Invalid params for sink '{self.name}'",
                details=[
                    {"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()
                ],
            ) from None

    @abstractmethod
    async def deliver(self, bundles: Iterable[dict], ctx: DeliveryContext) -> DeliveryResult: ...
