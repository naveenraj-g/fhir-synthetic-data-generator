from dependency_injector import containers, providers

from app.di.core import CoreContainer
from app.di.modules import GenerationContainer


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(packages=["app"])

    core = providers.Container(CoreContainer)

    generation = providers.Container(
        GenerationContainer,
        core=core,
    )


# The one process-wide Container instance. Lives here, not in app/main.py,
# so non-request-scoped internal modules (anything that isn't wired
# through FastAPI's Depends chain) can import this exact instance directly
# — `from app.di.container import container` — without reaching through
# app.main and risking a circular import (app.main imports deep into
# app.routers -> ... -> services -> repositories, and this container's own
# wiring() call scans that whole tree too). app/main.py imports this same
# object rather than constructing its own, so there is still only ever one
# Container (and therefore one core.database Singleton) per process; tests
# rely on that too (`container.core.database.override(...)` must override
# the exact instance every code path actually reads from).
container = Container()
