from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from ..config import settings


def normalized_database_url(url: str) -> str:
    # Railway currently supplies postgresql://...; explicitly select psycopg 3.
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


class Base(DeclarativeBase):
    pass


engine = create_engine(
    normalized_database_url(settings.database_url),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    # Phase 1 bootstrap. Replace create_all with Alembic before schema churn matters.
    from . import tables  # noqa: F401
    Base.metadata.create_all(bind=engine)
