"""Engine, sessao e criacao do schema."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import CONFIG
from .models import Base

_engine: Engine | None = None
_Sessao: sessionmaker | None = None


def engine(banco: Path | None = None) -> Engine:
    global _engine, _Sessao
    if _engine is None or banco is not None:
        caminho = banco or CONFIG.banco
        caminho.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{caminho}", future=True)

        @event.listens_for(_engine, "connect")
        def _pragmas(dbapi_conn, _):  # pragma: no cover - configuracao de driver
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        _Sessao = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def criar_schema(banco: Path | None = None) -> None:
    Base.metadata.create_all(engine(banco))


@contextmanager
def sessao(banco: Path | None = None) -> Iterator[Session]:
    """Sessao transacional: commit no sucesso, rollback em qualquer excecao."""
    engine(banco)
    assert _Sessao is not None
    s = _Sessao()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
