"""Planilha Qualis do ciclo — a conversao de artigo em pontos.

Nao ha download programatico estavel: a planilha e publicada por ciclo e por area
na Plataforma Sucupira. O conector le o arquivo que o projeto baixou, e a chave e
sempre (ciclo, area, ISSN) — porque o estrato muda com os dois primeiros.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

from sqlalchemy import select

from ..models import QualisStratum
from .base import ColetaVazia, Conector
from .brcris import normalizar_issn

COLUNAS = {
    "issn": ("issn", "issn do periodico", "issn_periodico"),
    "titulo": ("titulo", "título", "titulo do periodico", "periodico", "revista"),
    "estrato": ("estrato", "qualis", "classificacao", "classificação"),
    "area": ("area", "área", "area de avaliacao", "área de avaliação"),
}


def _achar(cabecalho: list[str], nomes: tuple[str, ...]) -> int | None:
    limpo = [c.strip().lower() for c in cabecalho]
    for nome in nomes:
        if nome in limpo:
            return limpo.index(nome)
    for i, c in enumerate(limpo):  # casamento por prefixo, para variacoes de rotulo
        if any(c.startswith(n) for n in nomes):
            return i
    return None


def linhas(caminho: Path) -> Iterator[list[str]]:
    with caminho.open(newline="", encoding="utf-8-sig", errors="replace") as fh:
        amostra = fh.read(4096)
        fh.seek(0)
        try:
            dialeto = csv.Sniffer().sniff(amostra, delimiters=";,\t")
        except csv.Error:
            dialeto = csv.excel
            dialeto.delimiter = ";"
        yield from csv.reader(fh, dialeto)


class ConectorQualis(Conector):
    nome = "qualis"

    def ingerir(self, caminho: Path, *, ciclo: str, area: str | None = None) -> int:
        caminho = Path(caminho)
        self.gravar_raw(caminho.read_bytes(), ref=caminho.name, media_type="text/csv")

        it = linhas(caminho)
        cabecalho = next(it, None)
        if not cabecalho:
            raise ColetaVazia(f"{caminho} vazio")
        idx = {k: _achar(cabecalho, v) for k, v in COLUNAS.items()}
        if idx["issn"] is None or idx["estrato"] is None:
            raise ColetaVazia(
                f"{caminho}: nao achei colunas de ISSN e estrato em {cabecalho[:8]}")

        n = 0
        for linha in it:
            if not linha or len(linha) <= idx["issn"]:
                continue
            issn = normalizar_issn(linha[idx["issn"]])
            estrato = (linha[idx["estrato"]] or "").strip().upper()
            if not issn or not estrato:
                continue
            area_linha = (linha[idx["area"]].strip() if idx["area"] is not None
                          and len(linha) > idx["area"] else None) or area
            if not area_linha:
                continue
            ja = self.s.scalar(select(QualisStratum).where(
                QualisStratum.ciclo == ciclo, QualisStratum.area_capes == area_linha,
                QualisStratum.issn == issn))
            if ja is not None:
                ja.estrato = estrato
                continue
            self.s.add(QualisStratum(
                ciclo=ciclo, area_capes=area_linha, issn=issn, estrato=estrato,
                titulo_periodico=(linha[idx["titulo"]].strip()
                                  if idx["titulo"] is not None
                                  and len(linha) > idx["titulo"] else None)))
            n += 1
        if n == 0:
            raise ColetaVazia(f"{caminho}: nenhuma linha de Qualis reconhecida")
        self.s.flush()
        return n
