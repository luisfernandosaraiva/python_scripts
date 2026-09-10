"""Contagens por pesquisador — a materia-prima da ficha e do futuro IPD."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Authorship,
    Bibliometrics,
    Faculty,
    Journal,
    Orientation,
    QualisStratum,
    TechnicalOutput,
    Work,
)

TIPOS = ("artigo", "evento", "capitulo", "livro", "preprint", "tese", "outro")


def obras_do_pesquisador(s: Session, pessoa: Faculty) -> list[Work]:
    return list(s.scalars(
        select(Work).join(Authorship).where(Authorship.faculty_id == pessoa.id)
        .order_by(Work.ano.desc().nullslast(), Work.titulo)).all())


def producao_por_ano(obras: list[Work]) -> list[dict[str, Any]]:
    """Serie anual por tipo — o grafico central da ficha do pesquisador."""
    por_ano: dict[int, Counter] = defaultdict(Counter)
    for obra in obras:
        if obra.ano:
            por_ano[obra.ano][obra.tipo or "outro"] += 1
    return [
        {"ano": ano, "total": sum(contagem.values()),
         **{tipo: contagem.get(tipo, 0) for tipo in TIPOS}}
        for ano, contagem in sorted(por_ano.items())
    ]


def _pct(parte: int, total: int) -> float:
    return round(parte / total * 100, 1) if total else 0.0


def indicadores_do_pesquisador(s: Session, pessoa: Faculty, *,
                               inicio: int, fim: int) -> dict[str, Any]:
    obras = obras_do_pesquisador(s, pessoa)
    no_periodo = [o for o in obras if o.ano and inicio <= o.ano <= fim]
    artigos = [o for o in obras if o.tipo == "artigo"]
    artigos_periodo = [o for o in no_periodo if o.tipo == "artigo"]

    orientacoes = list(s.scalars(select(Orientation).where(
        Orientation.faculty_id == pessoa.id)).all())
    tecnica = list(s.scalars(select(TechnicalOutput).where(
        TechnicalOutput.faculty_id == pessoa.id)).all())

    ids = [o.id for o in obras]
    biblio = list(s.scalars(select(Bibliometrics).where(
        Bibliometrics.work_id.in_(ids))).all()) if ids else []
    com_pais = [b for b in biblio if b.coautoria_estrangeira is not None]

    return {
        "obras_total": len(obras),
        "obras_periodo": len(no_periodo),
        "artigos_total": len(artigos),
        "artigos_periodo": len(artigos_periodo),
        "pct_doi_periodo": _pct(sum(1 for o in no_periodo if o.doi), len(no_periodo)),
        "pct_doi_artigos": _pct(sum(1 for o in artigos if o.doi), len(artigos)),
        "pct_periodico_periodo": _pct(sum(1 for o in no_periodo if o.issn),
                                      len(no_periodo)),
        "orientacoes": len(orientacoes),
        "orientacoes_por_nivel": dict(Counter(o.nivel or "nao_informado"
                                              for o in orientacoes)),
        "patentes": sum(1 for t in tecnica if t.tipo == "patente"),
        "software": sum(1 for t in tecnica if t.tipo == "software"),
        "citacoes": sum(b.citacoes or 0 for b in biblio),
        "pct_coautoria_estrangeira": _pct(
            sum(1 for b in com_pais if b.coautoria_estrangeira), len(com_pais)),
        "periodicos_distintos": len({o.issn for o in no_periodo if o.issn}),
        # Lacunas: sao elas que dizem quanto do indice ainda nao fecha.
        "sem_doi_sem_periodico": sum(1 for o in no_periodo if not o.doi and not o.issn),
        "ano_ambiguo": sum(1 for o in no_periodo if o.ano_ambiguo),
    }


def estrato_por_issn(s: Session, *, ciclo: str, area: str) -> dict[str, str]:
    """Tabela ISSN→estrato do ciclo e da area — o join que converte artigo em ponto."""
    linhas = s.scalars(select(QualisStratum).where(
        QualisStratum.ciclo == ciclo, QualisStratum.area_capes == area)).all()
    return {linha.issn: linha.estrato for linha in linhas}


def titulo_periodico(s: Session, obra: Work) -> str | None:
    if obra.journal_id:
        revista = s.get(Journal, obra.journal_id)
        if revista and revista.titulo:
            return revista.titulo
    return None
