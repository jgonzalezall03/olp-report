import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://olp_user:olp_pass@db:5432/olp_report"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def configure_database(url: str, **engine_kwargs):
    global engine, SessionLocal, DATABASE_URL
    DATABASE_URL = url
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, **engine_kwargs)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    from .models import Base as ModelsBase
    ModelsBase.metadata.create_all(bind=engine)
