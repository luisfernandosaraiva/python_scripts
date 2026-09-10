"""Casamento de obras — a cascata do §4, do sinal mais forte ao mais fraco.

1. DOI normalizado         -> chave forte, merge automatico
2. ISSN + ano + volume + pagina inicial -> forte o bastante para merge automatico
3. similaridade de titulo + ano ±1 acima do limiar -> **fila de revisao humana**
4. nada casou -> obra permanece isolada, marcada como nao resolvida

Nenhum merge por similaridade acontece sozinho: o par vai para
`work_match_decision` com decisao `pendente` e espera um humano. O percentual de
itens resolvidos por DOI e, ele proprio, o indicador de qualidade da base.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Authorship, Bibliometrics, Work, WorkMatchDecision

LIMIAR_TITULO = 0.92


def _similaridade(a: str, b: str) -> float:
    return SequenceMatcher(None, a or "", b or "").ratio()


def _fundir(s: Session, mantida: Work, descartada: Work) -> None:
    """Move autorias e bibliometria para a obra mantida e apaga a duplicata."""
    for autoria in list(descartada.authorships):
        existe = s.scalar(select(Authorship).where(
            Authorship.work_id == mantida.id,
            Authorship.faculty_id == autoria.faculty_id))
        if existe is None:
            autoria.work_id = mantida.id
        else:
            s.delete(autoria)
    if descartada.bibliometria and not mantida.bibliometria:
        descartada.bibliometria.work_id = mantida.id
    elif descartada.bibliometria:
        s.delete(descartada.bibliometria)

    for campo in ("doi", "issn", "ano", "volume", "pagina_inicial", "journal_id",
                  "raw_document_id"):
        if getattr(mantida, campo) in (None, "") and getattr(descartada, campo):
            setattr(mantida, campo, getattr(descartada, campo))
    s.flush()
    s.delete(descartada)
    s.flush()


def _registrar(s: Session, a: Work, b: Work, metodo: str, escore: float,
               decisao: str, por: str) -> None:
    s.add(WorkMatchDecision(work_a=a.id, work_b=b.id, metodo=metodo, escore=escore,
                            decisao=decisao, decidido_por=por))


def resolver_obras(s: Session, *, decidido_por: str = "obsppg.resolve") -> dict[str, int]:
    obras = list(s.scalars(select(Work)).all())
    resumo = {"por_doi": 0, "por_issn": 0, "pendentes_revisao": 0, "nao_resolvidas": 0}

    # 1. DOI -------------------------------------------------------------- #
    por_doi: dict[str, Work] = {}
    for obra in list(obras):
        if not obra.doi:
            continue
        primeira = por_doi.get(obra.doi)
        if primeira is None:
            por_doi[obra.doi] = obra
            obra.resolvido_por = "doi"
            continue
        _registrar(s, primeira, obra, "doi", 1.0, "merge", decidido_por)
        _fundir(s, primeira, obra)
        resumo["por_doi"] += 1

    obras = list(s.scalars(select(Work)).all())

    # 2. ISSN + ano + volume + pagina ------------------------------------- #
    chaves: dict[tuple, Work] = {}
    for obra in list(obras):
        if obra.doi or not (obra.issn and obra.ano):
            continue
        chave = (obra.issn, obra.ano, obra.volume or "", obra.pagina_inicial or "")
        if chave[2] == "" and chave[3] == "":
            continue  # sem volume nem pagina o sinal e fraco demais
        primeira = chaves.get(chave)
        if primeira is None:
            chaves[chave] = obra
            obra.resolvido_por = "issn_ano"
            continue
        _registrar(s, primeira, obra, "issn_ano_pagina", 0.95, "merge", decidido_por)
        _fundir(s, primeira, obra)
        resumo["por_issn"] += 1

    obras = [o for o in s.scalars(select(Work)).all() if not o.doi]

    # 3. titulo + ano ±1 -> fila de revisao ------------------------------- #
    ja_vistos = {
        (d.work_a, d.work_b) for d in s.scalars(select(WorkMatchDecision)).all()
    }
    for a, b in combinations(obras, 2):
        if not (a.titulo_normalizado and b.titulo_normalizado):
            continue
        if a.ano and b.ano and abs(a.ano - b.ano) > 1:
            continue
        if (a.id, b.id) in ja_vistos or (b.id, a.id) in ja_vistos:
            continue
        escore = _similaridade(a.titulo_normalizado, b.titulo_normalizado)
        if escore >= LIMIAR_TITULO:
            _registrar(s, a, b, "titulo_ano", escore, "pendente", decidido_por)
            resumo["pendentes_revisao"] += 1

    for obra in s.scalars(select(Work)).all():
        if not obra.resolvido_por or obra.resolvido_por == "nenhum":
            obra.resolvido_por = "nenhum"
            resumo["nao_resolvidas"] += 1

    s.flush()
    return resumo
