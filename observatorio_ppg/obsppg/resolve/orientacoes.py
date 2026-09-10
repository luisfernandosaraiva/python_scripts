"""Casamento de orientacoes entre fontes.

A mesma defesa de tese aparece no BrCris (`/api/orientacoes`) e no XML do Lattes.
Sem esta checagem o mesmo orientando entra duas vezes e a dimensao de formacao do
indice dobra — erro que so apareceria depois, ja dentro do IPD.

A chave e (docente, nivel, ano, nome do orientando normalizado). Nome e o unico
identificador que as duas fontes compartilham; por isso a comparacao ignora
acentos, pontuacao e caixa, e exige que nivel e ano batam.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ingest.brcris import normalizar_nome
from ..models import Orientation


def orientacao_equivalente(s: Session, *, faculty_id: int, nivel: str | None,
                           ano: int | None, orientando: str | None) -> Orientation | None:
    """Devolve a orientacao ja gravada que descreve o mesmo evento, se houver."""
    if not orientando:
        return None
    alvo = normalizar_nome(orientando)
    if not alvo:
        return None
    candidatas = s.scalars(select(Orientation).where(
        Orientation.faculty_id == faculty_id)).all()
    for candidata in candidatas:
        if not candidata.orientando or normalizar_nome(candidata.orientando) != alvo:
            continue
        if nivel and candidata.nivel and nivel != candidata.nivel:
            continue
        if ano and candidata.ano and ano != candidata.ano:
            continue
        return candidata
    return None
