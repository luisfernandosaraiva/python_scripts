"""Exporta o estado do banco para o JSON que a interface le.

A interface e descartavel por desenho: nao ha regra de negocio nela, e este
arquivo e o unico contrato entre o motor e a tela. Trocar Streamlit, React ou o
HTML estatico por outra coisa nao toca em nada do `obsppg/`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import CONFIG
from ..metrics.indicadores import (
    estrato_por_issn,
    indicadores_do_pesquisador,
    obras_do_pesquisador,
    producao_por_ano,
    titulo_periodico,
)
from ..models import (
    PPG,
    Faculty,
    Membership,
    Orientation,
    SyncRun,
    TechnicalOutput,
)


def _ppg_do_pesquisador(s: Session, pessoa: Faculty) -> tuple[str | None, str | None]:
    vinculo = s.scalar(
        select(Membership).where(Membership.faculty_id == pessoa.id)
        .order_by(Membership.id.desc()))
    if vinculo is None:
        return None, None
    ppg = s.get(PPG, vinculo.ppg_id)
    return (ppg.sigla if ppg else None), vinculo.categoria


def exportar(s: Session, destino: Path | None = None, *,
             inicio: int = 2021, fim: int = 2024,
             ciclo_qualis: str | None = None,
             area_qualis: str | None = None) -> Path:
    destino = Path(destino or CONFIG.export)
    destino.parent.mkdir(parents=True, exist_ok=True)

    estratos = (estrato_por_issn(s, ciclo=ciclo_qualis, area=area_qualis)
                if ciclo_qualis and area_qualis else {})

    pesquisadores: list[dict[str, Any]] = []
    for pessoa in s.scalars(select(Faculty).order_by(Faculty.full_name)).all():
        obras = obras_do_pesquisador(s, pessoa)
        sigla, categoria = _ppg_do_pesquisador(s, pessoa)
        pesquisadores.append({
            "id": pessoa.id,
            "nome": pessoa.full_name,
            "nome_exibicao": pessoa.display_name or pessoa.full_name,
            "lattes_id": pessoa.lattes_id,          # string: pode ter zero a esquerda
            "orcid": pessoa.orcid,
            "brcris_id": pessoa.brcris_id,
            "curriculo_atualizado_em": (pessoa.curriculo_atualizado_em.isoformat()
                                        if pessoa.curriculo_atualizado_em else None),
            "ppg": sigla,
            "categoria": categoria,
            "nomes_citacao": [c.name for c in pessoa.citation_names],
            "indicadores": indicadores_do_pesquisador(s, pessoa, inicio=inicio, fim=fim),
            "producao_por_ano": producao_por_ano(obras),
            "obras": [{
                "id": o.id,
                "titulo": o.titulo,
                "tipo": o.tipo,
                "ano": o.ano,
                "ano_ambiguo": bool(o.ano_ambiguo),
                "doi": o.doi,
                "issn": o.issn,
                "periodico": titulo_periodico(s, o),
                "estrato": estratos.get(o.issn or ""),
                "citacoes": o.bibliometria.citacoes if o.bibliometria else None,
                "coautoria_estrangeira": (o.bibliometria.coautoria_estrangeira
                                          if o.bibliometria else None),
                "fonte": o.fonte,
            } for o in obras],
            "orientacoes": [{
                "orientando": o.orientando, "nivel": o.nivel, "papel": o.papel,
                "ano": o.ano, "situacao": o.situacao, "fonte": o.fonte,
            } for o in s.scalars(select(Orientation).where(
                Orientation.faculty_id == pessoa.id)
                .order_by(Orientation.ano.desc().nullslast())).all()],
            "tecnica": [{
                "tipo": t.tipo, "titulo": t.titulo, "ano": t.ano,
                "situacao": t.situacao, "numero": t.numero, "fonte": t.fonte,
            } for t in s.scalars(select(TechnicalOutput).where(
                TechnicalOutput.faculty_id == pessoa.id)
                .order_by(TechnicalOutput.ano.desc().nullslast())).all()],
        })

    coletas = [{
        "fonte": r.source, "status": r.status,
        "inicio": r.started_at.isoformat() if r.started_at else None,
        "fim": r.finished_at.isoformat() if r.finished_at else None,
        "documentos": r.n_documents, "erro": r.error,
    } for r in s.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(30)).all()]

    dados = {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "periodo": {"inicio": inicio, "fim": fim},
        "qualis": {"ciclo": ciclo_qualis, "area": area_qualis,
                   "periodicos_com_estrato": len(estratos)},
        "ppgs": [{
            "sigla": p.sigla, "nome": p.nome, "codigo_capes": p.codigo_capes,
            "area_capes": p.area_capes, "niveis": p.niveis,
            "n_docentes": len({m.faculty_id for m in p.memberships}),
        } for p in s.scalars(select(PPG).order_by(PPG.sigla)).all()],
        "coletas": coletas,
        "pesquisadores": pesquisadores,
    }
    destino.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    return destino
