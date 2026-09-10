"""Dados Abertos da CAPES (Sucupira) — a fonte oficial do vinculo docente↔PPG.

A CAPES publica planilha por coleta e por ano; os rotulos de coluna mudam entre
anos, entao o conector procura cada campo por uma lista de nomes aceitos. Esta e
a unica fonte, junto com a secretaria do PPG, de onde o vinculo pode vir — nunca
do BrCris, onde o campo veio vazio em toda a amostra.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from ..models import PPG, Faculty, Membership, MembershipSnapshot
from .base import ColetaVazia, Conector
from .qualis import _achar, linhas

COLUNAS = {
    "lattes": ("id_lattes", "id lattes", "identificador lattes", "nr_documento_docente"),
    "nome": ("nm_docente", "nome do docente", "nome", "nm_discente"),
    "categoria": ("ds_categoria_docente", "categoria", "ds_tipo_vinculo_docente_ies"),
    "programa": ("nm_programa_ies", "programa", "nm_programa"),
    "codigo": ("cd_programa_ies", "codigo do programa", "cd_programa"),
    "ano": ("an_base", "ano", "ano base"),
}

CATEGORIAS = {"PERMANENTE": "permanente", "COLABORADOR": "colaborador",
              "VISITANTE": "visitante"}


class ConectorCAPES(Conector):
    nome = "capes_aberto"

    def ingerir_vinculos(self, caminho: Path, *, sigla_ppg: str,
                         codigo_capes: str | None = None) -> int:
        caminho = Path(caminho)
        self.gravar_raw(caminho.read_bytes(), ref=caminho.name, media_type="text/csv")

        it = linhas(caminho)
        cabecalho = next(it, None)
        if not cabecalho:
            raise ColetaVazia(f"{caminho} vazio")
        idx = {k: _achar(cabecalho, v) for k, v in COLUNAS.items()}
        if idx["lattes"] is None and idx["nome"] is None:
            raise ColetaVazia(
                f"{caminho}: sem coluna de ID Lattes nem de nome em {cabecalho[:8]}")

        ppg = self.s.scalar(select(PPG).where(PPG.sigla == sigla_ppg))
        if ppg is None:
            ppg = PPG(sigla=sigla_ppg, nome=sigla_ppg, codigo_capes=codigo_capes)
            self.s.add(ppg)
            self.s.flush()

        assert self.run is not None
        foto = MembershipSnapshot(ppg_id=ppg.id, sync_run_id=self.run.id,
                                  fonte=self.nome)
        self.s.add(foto)
        self.s.flush()

        def celula(linha: list[str], chave: str) -> str | None:
            i = idx[chave]
            if i is None or len(linha) <= i:
                return None
            return (linha[i] or "").strip() or None

        n = 0
        for linha in it:
            if not linha:
                continue
            if codigo_capes and celula(linha, "codigo") and \
                    celula(linha, "codigo") != codigo_capes:
                continue
            lattes = celula(linha, "lattes")
            nome = celula(linha, "nome")
            if not (lattes or nome):
                continue

            pessoa = None
            if lattes:
                pessoa = self.s.scalar(select(Faculty).where(Faculty.lattes_id == lattes))
            if pessoa is None and nome:
                pessoa = self.s.scalar(select(Faculty).where(Faculty.full_name == nome))
            if pessoa is None:
                pessoa = Faculty(full_name=nome or lattes, lattes_id=lattes)
                self.s.add(pessoa)
                self.s.flush()

            ano = celula(linha, "ano")
            self.s.add(Membership(
                faculty_id=pessoa.id, ppg_id=ppg.id, snapshot_id=foto.id,
                categoria=CATEGORIAS.get((celula(linha, "categoria") or "").upper()),
                inicio=int(ano) if ano and ano.isdigit() else None,
                fonte=self.nome))
            n += 1

        anteriores = len(self.s.scalars(select(Membership).where(
            Membership.ppg_id == ppg.id, Membership.fonte == self.nome)).all()) - n
        self.exigir_nao_vazio(range(n), f"vinculos de {sigla_ppg}", max(anteriores, 0))
        foto.n_docentes = n
        self.s.flush()
        return n
