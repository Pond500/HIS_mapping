"""
database.py
===========
PostgreSQL engine + session. Models live in app/models.py.
Schema changes go through Alembic (alembic/versions), not create_all.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]  # set in .env (see .env.example)

# pool_pre_ping: survive a database restart instead of failing every later request
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
