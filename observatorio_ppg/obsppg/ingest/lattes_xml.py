"""Parser do XML do Lattes (XSD do CNPq).

O mesmo parser serve as duas origens, e essa e a razao de comecar pelo XML
individual em vez de por raspagem: o Extrator institucional entrega currículos
no **mesmo XSD** que o docente baixa do proprio curriculo. Quando o convenio
sair, muda a origem do arquivo, nao o codigo.

Leitura defensiva por proposito: os nomes de atributo variam entre versoes do
XSD, entao cada campo e procurado por uma lista de nomes aceitos e o elemento
por prefixo de tag (`DADOS-BASICOS-*`, `DETALHAMENTO-*`).
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree as ET

from sqlalchemy import select

from ..models import Authorship, CitationName, Faculty, Orientation, TechnicalOutput, Work
from .base import ColetaVazia, Conector
from .brcris import normalizar_doi, normalizar_issn, normalizar_titulo

# O Lattes exporta em ISO-8859-1; alguns exports recentes vem em UTF-8.
CODIFICACOES = ("iso-8859-1", "utf-8", "cp1252")


def _texto(caminho: Path) -> str:
    dados = caminho.read_bytes()
    for cod in CODIFICACOES:
        try:
            return dados.decode(cod)
        except UnicodeDecodeError:
            continue
    return dados.decode("iso-8859-1", errors="replace")


def abrir_curriculos(origem: Path) -> Iterator[tuple[str, str]]:
    """Devolve (nome_do_arquivo, xml) para .xml, .zip ou diretorio com ambos."""
    if origem.is_dir():
        for filho in sorted(origem.iterdir()):
            if filho.suffix.lower() in (".xml", ".zip"):
                yield from abrir_curriculos(filho)
        return
    if origem.suffix.lower() == ".zip":
        with zipfile.ZipFile(origem) as z:
            for nome in z.namelist():
                if nome.lower().endswith(".xml"):
                    bruto = z.read(nome)
                    for cod in CODIFICACOES:
                        try:
                            yield f"{origem.name}:{nome}", bruto.decode(cod)
                            break
                        except UnicodeDecodeError:
                            continue
        return
    if origem.suffix.lower() == ".xml":
        yield origem.name, _texto(origem)


def attr(el: ET.Element | None, *nomes: str) -> str | None:
    if el is None:
        return None
    for nome in nomes:
        v = el.get(nome)
        if v not in (None, ""):
            return v.strip()
    return None


def filho_por_prefixo(el: ET.Element, prefixo: str) -> ET.Element | None:
    for filho in el:
        if filho.tag.upper().startswith(prefixo):
            return filho
    return None


def ano_de(*valores: Any) -> int | None:
    for v in valores:
        if not v:
            continue
        m = re.search(r"(1[89]\d{2}|20\d{2})", str(v))
        if m:
            return int(m.group(1))
    return None


class ConectorLattesXML(Conector):
    """Le currículos em XML e grava producao, orientacoes e PTT.

    Papel no piloto, depois da sondagem: **conferencia**. Tapa as obras sem DOI e
    sem periodico e valida as datas ambiguas — deixou de ser a fonte principal.
    """

    nome = "lattes_xml"

    def ingerir(self, origem: Path) -> dict[str, int]:
        origem = Path(origem)
        if not origem.exists():
            raise FileNotFoundError(f"{origem} nao existe")

        totais = {"curriculos": 0, "obras": 0, "orientacoes": 0, "ptt": 0}
        for nome_arquivo, xml in abrir_curriculos(origem):
            doc = self.gravar_raw(xml, ref=nome_arquivo, media_type="application/xml")
            raiz = ET.fromstring(xml)
            pessoa = self._pessoa(raiz)
            if pessoa is None:
                continue
            totais["curriculos"] += 1
            totais["obras"] += self._producao(raiz, pessoa, doc.id)
            totais["orientacoes"] += self._orientacoes(raiz, pessoa)
            totais["ptt"] += self._tecnica(raiz, pessoa)

        if totais["curriculos"] == 0:
            raise ColetaVazia(f"nenhum curriculo valido em {origem}")
        self.s.flush()
        return totais

    # ---------------- pessoa ---------------- #
    def _pessoa(self, raiz: ET.Element) -> Faculty | None:
        lattes = attr(raiz, "NUMERO-IDENTIFICADOR")  # TEXT: preserva zero a esquerda
        gerais = raiz.find("DADOS-GERAIS")
        nome = attr(gerais, "NOME-COMPLETO")
        if not (lattes or nome):
            return None

        pessoa = None
        if lattes:
            pessoa = self.s.scalar(select(Faculty).where(Faculty.lattes_id == lattes))
        if pessoa is None and nome:
            pessoa = self.s.scalar(select(Faculty).where(Faculty.full_name == nome))
        if pessoa is None:
            pessoa = Faculty(full_name=nome or lattes or "")
            self.s.add(pessoa)
        pessoa.lattes_id = lattes or pessoa.lattes_id
        pessoa.full_name = nome or pessoa.full_name

        atualizacao = attr(raiz, "DATA-ATUALIZACAO")
        if atualizacao and len(atualizacao) == 8:
            from datetime import date
            try:
                pessoa.curriculo_atualizado_em = date(int(atualizacao[4:]),
                                                      int(atualizacao[2:4]),
                                                      int(atualizacao[:2]))
            except ValueError:
                pass
        self.s.flush()

        for assinatura in (attr(gerais, "NOME-EM-CITACOES-BIBLIOGRAFICAS") or "").split(";"):
            assinatura = assinatura.strip()
            if not assinatura:
                continue
            ja = self.s.scalar(select(CitationName).where(
                CitationName.faculty_id == pessoa.id, CitationName.name == assinatura))
            if ja is None:
                self.s.add(CitationName(faculty_id=pessoa.id, name=assinatura,
                                        source=self.nome))
        self.s.flush()
        return pessoa

    # ---------------- producao bibliografica ---------------- #
    SECOES = (
        ("ARTIGO-PUBLICADO", "artigo",
         ("TITULO-DO-ARTIGO", "TITULO-DO-ARTIGO-INGLES"), ("ANO-DO-ARTIGO",)),
        ("TRABALHO-EM-EVENTOS", "evento",
         ("TITULO-DO-TRABALHO", "TITULO-DO-TRABALHO-INGLES"), ("ANO-DO-TRABALHO",)),
        ("CAPITULO-DE-LIVRO-PUBLICADO", "capitulo",
         ("TITULO-DO-CAPITULO-DO-LIVRO",), ("ANO",)),
        ("LIVRO-PUBLICADO-OU-ORGANIZADO", "livro", ("TITULO-DO-LIVRO",), ("ANO",)),
    )

    def _producao(self, raiz: ET.Element, pessoa: Faculty, raw_id: int) -> int:
        n = 0
        for tag, tipo, campos_titulo, campos_ano in self.SECOES:
            for item in raiz.iter(tag):
                basicos = filho_por_prefixo(item, "DADOS-BASICOS")
                detalhe = filho_por_prefixo(item, "DETALHAMENTO")
                titulo = attr(basicos, *campos_titulo)
                if not titulo:
                    continue
                doi = normalizar_doi(attr(basicos, "DOI"))
                issn = normalizar_issn(attr(detalhe, "ISSN"))
                ano = ano_de(attr(basicos, *campos_ano), attr(detalhe, "ANO"))

                obra = None
                if doi:
                    obra = self.s.scalar(select(Work).where(Work.doi == doi))
                if obra is None:
                    obra = self.s.scalar(select(Work).where(
                        Work.titulo_normalizado == normalizar_titulo(titulo),
                        Work.ano == ano))
                if obra is None:
                    obra = Work(titulo=titulo, fonte=self.nome,
                                fonte_ref=f"{pessoa.lattes_id}:{tag}:{n}")
                    self.s.add(obra)
                    n += 1
                # O XML e a fonte de conferencia: so preenche o que falta.
                obra.titulo_normalizado = normalizar_titulo(titulo)
                obra.tipo = obra.tipo or tipo
                obra.ano = obra.ano or ano
                obra.doi = obra.doi or doi
                obra.issn = obra.issn or issn
                obra.volume = obra.volume or attr(detalhe, "VOLUME")
                obra.pagina_inicial = obra.pagina_inicial or attr(detalhe, "PAGINA-INICIAL")
                obra.raw_document_id = obra.raw_document_id or raw_id
                if doi and obra.resolvido_por in (None, "nenhum"):
                    obra.resolvido_por = "doi"
                self.s.flush()

                ja = self.s.scalar(select(Authorship).where(
                    Authorship.work_id == obra.id, Authorship.faculty_id == pessoa.id))
                if ja is None:
                    autores = list(item.iter("AUTORES"))
                    posicao = next((int(attr(a, "ORDEM-DE-AUTORIA") or 0) for a in autores
                                    if (attr(a, "NOME-COMPLETO-DO-AUTOR") or "").upper()
                                    == (pessoa.full_name or "").upper()), None)
                    self.s.add(Authorship(work_id=obra.id, faculty_id=pessoa.id,
                                          posicao=posicao or None, fonte=self.nome))
        self.s.flush()
        return n

    # ---------------- orientacoes ---------------- #
    NIVEL_POR_TAG = {
        "MESTRADO": "mestrado", "DOUTORADO": "doutorado",
        "POS-DOUTORADO": "pos_doutorado", "INICIACAO-CIENTIFICA": "iniciacao",
    }

    def _orientacoes(self, raiz: ET.Element, pessoa: Faculty) -> int:
        n = 0
        for bloco in raiz.iter("ORIENTACOES-CONCLUIDAS"):
            for item in bloco:
                tag = item.tag.upper()
                nivel = next((v for k, v in self.NIVEL_POR_TAG.items() if k in tag),
                             "nao_informado")
                basicos = filho_por_prefixo(item, "DADOS-BASICOS")
                detalhe = filho_por_prefixo(item, "DETALHAMENTO")
                titulo = attr(basicos, "TITULO")
                orientando = attr(detalhe, "NOME-DO-ORIENTADO", "NOME-DO-ORIENTANDO")
                if not (titulo or orientando):
                    continue
                ref = f"{pessoa.lattes_id}:{tag}:{normalizar_titulo(titulo or orientando or '')[:80]}"
                ja = self.s.scalar(select(Orientation).where(
                    Orientation.faculty_id == pessoa.id, Orientation.fonte == self.nome,
                    Orientation.fonte_ref == ref))
                if ja is not None:
                    continue
                tipo = (attr(detalhe, "TIPO-DE-ORIENTACAO") or "").upper()
                ano = ano_de(attr(basicos, "ANO"))
                # a mesma defesa pode ja ter vindo do /api/orientacoes do BrCris
                from ..resolve.orientacoes import orientacao_equivalente
                gemea = orientacao_equivalente(self.s, faculty_id=pessoa.id, nivel=nivel,
                                               ano=ano, orientando=orientando)
                if gemea is not None:
                    gemea.nivel = gemea.nivel if gemea.nivel != "nao_informado" else nivel
                    gemea.ano = gemea.ano or ano
                    gemea.papel = ("coorientacao" if "CO_ORIENT" in tipo
                                   or "COORIENT" in tipo else gemea.papel)
                    gemea.fonte_ref = gemea.fonte_ref or ref
                    continue
                self.s.add(Orientation(
                    faculty_id=pessoa.id, orientando=orientando, nivel=nivel,
                    papel="coorientacao" if "CO_ORIENT" in tipo or "COORIENT" in tipo
                          else "orientacao",
                    ano=ano, situacao="concluida", fonte=self.nome, fonte_ref=ref))
                n += 1
        self.s.flush()
        return n

    # ---------------- producao tecnica ---------------- #
    def _tecnica(self, raiz: ET.Element, pessoa: Faculty) -> int:
        n = 0
        for tag, tipo in (("PATENTE", "patente"), ("SOFTWARE", "software"),
                          ("CULTIVAR-REGISTRADA", "cultivar"), ("MARCA", "marca")):
            for item in raiz.iter(tag):
                basicos = filho_por_prefixo(item, "DADOS-BASICOS")
                detalhe = filho_por_prefixo(item, "DETALHAMENTO")
                titulo = attr(basicos, "TITULO", "TITULO-DO-SOFTWARE")
                if not titulo:
                    continue
                ref = f"{pessoa.lattes_id}:{tag}:{normalizar_titulo(titulo)[:80]}"
                ja = self.s.scalar(select(TechnicalOutput).where(
                    TechnicalOutput.faculty_id == pessoa.id,
                    TechnicalOutput.fonte == self.nome,
                    TechnicalOutput.fonte_ref == ref))
                if ja is not None:
                    continue
                self.s.add(TechnicalOutput(
                    faculty_id=pessoa.id, tipo=tipo, titulo=titulo,
                    ano=ano_de(attr(basicos, "ANO", "ANO-DESENVOLVIMENTO")),
                    numero=attr(detalhe, "NUMERO-DO-REGISTRO", "CODIGO-DO-REGISTRO"),
                    situacao=attr(detalhe, "SITUACAO-DO-PEDIDO", "CATEGORIA"),
                    fonte=self.nome, fonte_ref=ref))
                n += 1
        self.s.flush()
        return n
