"""ORCID — ponte entre o Lattes e as bases internacionais.

Nao e fonte de producao no piloto: serve para confirmar o par pessoa↔obra que o
proprio autor declarou, e para pescar DOI de obras que chegaram sem ele.
"""

from __future__ import annotations

from sqlalchemy import select

from ..config import CONFIG
from ..models import Faculty
from .base import ClienteHTTP, Conector
from .brcris import normalizar_doi


class ConectorORCID(Conector):
    nome = "orcid"

    def __init__(self, s, cliente: ClienteHTTP | None = None, **kw):
        super().__init__(s, **kw)
        self.api = cliente or ClienteHTTP(CONFIG.orcid_base)

    def dois_declarados(self, pessoa: Faculty) -> list[str]:
        """DOIs que o proprio pesquisador declarou no ORCID."""
        if not pessoa.orcid:
            return []
        dados = self.api.get(f"/{pessoa.orcid}/works")
        self.gravar_raw(dados, ref=f"works/{pessoa.orcid}")
        achados: list[str] = []
        for grupo in dados.get("group", []):
            for ident in (grupo.get("external-ids") or {}).get("external-id", []):
                if (ident.get("external-id-type") or "").lower() == "doi":
                    doi = normalizar_doi(ident.get("external-id-value"))
                    if doi and doi not in achados:
                        achados.append(doi)
        return achados

    def ingerir(self) -> dict[str, int]:
        pessoas = self.s.scalars(select(Faculty).where(Faculty.orcid.isnot(None))).all()
        return {p.display_name or p.full_name: len(self.dois_declarados(p))
                for p in pessoas}
