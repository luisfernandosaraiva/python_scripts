"""Enriquecimento bibliometrico por DOI — OpenAlex, com Crossref de reserva.

Entra depois da resolucao de obras porque a chave e o DOI: 73,1% das obras do
quadrienio o tem, e e por ele que se obtem citacoes, periodico canonico e a
coautoria internacional que alimenta a dimensao I do indice.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select

from ..config import CONFIG
from ..models import Bibliometrics, Work
from .base import ClienteHTTP, Conector

LOTE_DOI = 50  # limite pratico do filtro doi: com OR no OpenAlex


class ConectorOpenAlex(Conector):
    nome = "openalex"

    def __init__(self, s, cliente: ClienteHTTP | None = None,
                 crossref: ClienteHTTP | None = None, **kw):
        super().__init__(s, **kw)
        self.api = cliente or ClienteHTTP(CONFIG.openalex_base)
        self.crossref = crossref or ClienteHTTP(CONFIG.crossref_base)

    def obras_pendentes(self) -> list[Work]:
        """Obras com DOI e ainda sem linha de bibliometria."""
        return list(self.s.scalars(
            select(Work).outerjoin(Bibliometrics)
            .where(Work.doi.isnot(None), Bibliometrics.id.is_(None))).all())

    def ingerir(self, obras: Sequence[Work] | None = None) -> int:
        pendentes = list(obras) if obras is not None else self.obras_pendentes()
        if not pendentes:
            return 0
        por_doi = {o.doi: o for o in pendentes if o.doi}
        n = 0
        dois = list(por_doi)
        for inicio in range(0, len(dois), LOTE_DOI):
            fatia = dois[inicio:inicio + LOTE_DOI]
            params = {"filter": "doi:" + "|".join(fatia), "per-page": LOTE_DOI}
            if CONFIG.contato:
                params["mailto"] = CONFIG.contato
            dados = self.api.get("/works", params=params)
            self.gravar_raw(dados, ref=f"works/lote/{inicio // LOTE_DOI}")
            encontrados = set()
            for item in dados.get("results", []):
                doi = (item.get("doi") or "").replace("https://doi.org/", "").lower()
                obra = por_doi.get(doi)
                if obra is None:
                    continue
                encontrados.add(doi)
                self._gravar(obra, item)
                n += 1
            # DOI que o OpenAlex nao conhece cai para o Crossref, que cobre
            # periodicos nacionais com registro mais recente.
            for doi in (d for d in fatia if d not in encontrados):
                if self._crossref(por_doi[doi], doi):
                    n += 1
        self.s.flush()
        return n

    def _gravar(self, obra: Work, item: dict) -> None:
        paises = sorted({
            (inst or {}).get("country_code")
            for autoria in item.get("authorships", [])
            for inst in autoria.get("institutions", [])
            if (inst or {}).get("country_code")
        })
        fonte_local = ((item.get("primary_location") or {}).get("source") or {})
        obra.issn = obra.issn or fonte_local.get("issn_l")
        obra.ano = obra.ano or item.get("publication_year")

        percentil = (item.get("cited_by_percentile_year") or {}).get("max")
        self.s.merge(Bibliometrics(
            id=obra.bibliometria.id if obra.bibliometria else None,
            work_id=obra.id,
            openalex_id=(item.get("id") or "").rsplit("/", 1)[-1] or None,
            citacoes=item.get("cited_by_count"),
            percentil_area=float(percentil) if percentil is not None else None,
            coautoria_estrangeira=bool([p for p in paises if p != "BR"]),
            paises=",".join(paises)[:300] or None,
            fonte="openalex"))

    def _crossref(self, obra: Work, doi: str) -> bool:
        try:
            dados = self.crossref.get(f"/works/{doi}")
        except Exception:
            return False
        msg = dados.get("message") or {}
        self.gravar_raw(dados, ref=f"crossref/{doi}")
        obra.ano = obra.ano or (msg.get("issued", {}).get("date-parts") or [[None]])[0][0]
        issns = msg.get("ISSN") or []
        obra.issn = obra.issn or (issns[0] if issns else None)
        self.s.merge(Bibliometrics(
            id=obra.bibliometria.id if obra.bibliometria else None,
            work_id=obra.id, citacoes=msg.get("is-referenced-by-count"),
            fonte="crossref"))
        return True
