from collections.abc import Callable
from typing import Generic, TypeVar

from app.generator.errors import InvalidSpecError

T = TypeVar("T")


class Registry(Generic[T]):
    """Maps a string name (the `type` in config / the slicer name in a spec)
    to an implementation class. Registration happens via decorator at import
    time; see app/generator/__init__.py for the imports that trigger it."""

    def __init__(self, kind: str):
        self.kind = kind
        self._items: dict[str, type[T]] = {}

    def register(self, name: str) -> Callable[[type[T]], type[T]]:
        def decorator(cls: type[T]) -> type[T]:
            if name in self._items:
                raise ValueError(f"{self.kind} '{name}' is already registered")
            cls.name = name  # type: ignore[attr-defined]
            self._items[name] = cls
            return cls

        return decorator

    def get(self, name: str) -> type[T]:
        try:
            return self._items[name]
        except KeyError:
            raise InvalidSpecError(
                f"Unknown {self.kind} '{name}'. Available: {sorted(self._items)}"
            ) from None

    def __contains__(self, name: str) -> bool:
        return name in self._items

    def names(self) -> list[str]:
        return sorted(self._items)


connectors: Registry = Registry("connector")
slicers: Registry = Registry("slicer")
sinks: Registry = Registry("sink")
