from dependency_injector import containers, providers

from app.core.config import settings
from app.core.database import Database


class CoreContainer(containers.DeclarativeContainer):
    database = providers.Singleton(
        Database,
        db_url=settings.DATABASE_URL,
    )
