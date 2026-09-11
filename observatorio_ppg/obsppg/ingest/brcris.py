"""Conector do BrCris (Ibict).

Papel no desenho, fixado pela sondagem do §11–12 do documento de decisao:

* **resolve identidade** — ID Lattes limpo, ORCID e variacoes de nome de citacao;
* **entrega estrutura oficial do PPG** — codigo CAPES e area de avaliacao;
* **adianta a producao** — obras, orientacoes e patentes por pesquisador.

E o que ele **nao** e: fonte do vinculo docente↔PPG. O campo `program` veio vazio
em toda a amostra testada, e `affiliation` esta vazio para os 11 docentes do piloto.
Vinculo e categoria vem sempre da secretaria ou dos dados abertos da CAPES.

A API nao e publicada nem documentada pelo Ibict. Os endpoints e formatos abaixo
seguem o que a sondagem de 09/09/2026 observou; se o site mudar, o erro aparece
como `ErroDeFonte` com as chaves recebidas, que e o que torna o conserto rapido.
"""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any, Iterable, Sequence

from sqlalchemy import select

from ..config import CONFIG
from ..models import (
    Authorship,
    CitationName,
    Faculty,
    FacultyIdentifier,
    Journal,
    Orientation,
    TechnicalOutput,
    Work,
)
from .base import ClienteHTTP, Conector, ErroDeFonte

LOTE = 50  # o filtro _id/any recupera ate 50 documentos por chamada

TIPOS = [
    ("artigo", ("article", "artigo", "journal")),
    ("preprint", ("preprint",)),
    ("evento", ("conference", "evento", "proceeding", "congresso")),
    ("capitulo", ("chapter", "capitulo", "capítulo")),
    ("livro", ("book", "livro")),
    ("tese", ("thesis", "tese", "dissert", "doctoral", "master")),
]

NIVEIS = [
    ("doutorado", ("doutorado", "doctoral", "phd", "tese")),
    ("mestrado", ("mestrado", "master", "dissert")),
    ("pos_doutorado", ("pos-doutorado", "pós-doutorado", "postdoc")),
    ("iniciacao", ("iniciacao", "iniciação", "undergrad")),
]


# --------------------------------------------------------------------------- #
# helpers de leitura defensiva
# --------------------------------------------------------------------------- #
def valor(campo: Any) -> Any:
    """Desembrulha o formato Elastic Search-UI (`{"raw": ...}`) e devolve escalar."""
    if isinstance(campo, dict):
        for chave in ("raw", "value", "snippet"):
            if chave in campo:
                return valor(campo[chave])
        return campo
    if isinstance(campo, list):
        return [valor(x) for x in campo]
    return campo


def primeiro(campo: Any) -> Any:
    v = valor(campo)
    if isinstance(v, list):
        return v[0] if v else None
    return v


def lista(campo: Any) -> list[Any]:
    v = valor(campo)
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def normalizar_nome(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]+", " ", sem_acento.lower()).strip()


def normalizar_titulo(titulo: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", sem_acento.lower())).strip()


def normalizar_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = str(doi).strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return d or None


def normalizar_issn(issn: str | None) -> str | None:
    if not issn:
        return None
    limpo = re.sub(r"[^0-9xX]", "", str(issn)).upper()
    return f"{limpo[:4]}-{limpo[4:8]}" if len(limpo) == 8 else None


def classificar(texto: str | None, tabela: Sequence[tuple[str, tuple[str, ...]]],
                padrao: str) -> str:
    alvo = normalizar_nome(str(texto or ""))
    for rotulo, marcas in tabela:
        if any(m in alvo for m in marcas):
            return rotulo
    return padrao


def anos_de(data: Any) -> list[int]:
    """Extrai todos os anos citados em `publicationDate`.

    58 obras do quadriênio trazem mais de um ano no campo — por isso a funcao
    devolve lista, e quem chama decide o desempate (e marca `ano_ambiguo`).
    """
    achados: list[int] = []
    for parte in lista(data):
        for m in re.finditer(r"(1[89]\d{2}|20\d{2})", str(parte)):
            ano = int(m.group(1))
            if ano not in achados:
                achados.append(ano)
    return achados


# --------------------------------------------------------------------------- #
# cliente
# --------------------------------------------------------------------------- #
class BrCris(ClienteHTTP):
    """Chamadas cruas a API do BrCris."""

    def __init__(self, base: str | None = None, carga: str | None = None, **kw: Any):
        super().__init__(base or CONFIG.brcris_base, **kw)
        self.carga = carga or CONFIG.brcris_carga
        # preenchido na primeira busca bem-sucedida; ver FORMATOS
        self.formato: str | None = None

    def indice(self, nome: str) -> str:
        return f"brc-{self.carga}-{nome}-v2"

    # ---- busca principal ---- #
    # O corpo aceito pelo /api/search nao e' publicado. A sondagem observou o
    # formato `requestState`/`queryConfig` do Elastic Search-UI, mas a primeira
    # coleta real recebeu 400 "Search term or filters are required" — ou seja, o
    # servidor procura os campos em outro lugar. Em vez de chutar um formato por
    # vez a cada ida e volta, o cliente **negocia**: tenta os candidatos em ordem,
    # guarda o que funcionou e usa so ele daí em diante.
    FORMATOS = ("requestState", "plano", "state", "misto")

    def _corpo(self, formato: str, indice: str, termo: str, filtros: list[dict],
               campos: Sequence[str], busca_em: Sequence[str], tamanho: int,
               pagina: int) -> dict:
        estado = {
            "searchTerm": termo,
            "filters": filtros,
            "resultsPerPage": tamanho,
            "current": pagina,
        }
        config = {
            "index": self.indice(indice),
            "search_fields": {c: {} for c in busca_em},
            "result_fields": {c: {"raw": {}} for c in campos},
            "facets": {},
        }
        if formato == "requestState":
            return {"requestState": estado, "queryConfig": config}
        if formato == "plano":
            return {**estado, **config}
        if formato == "state":
            return {"state": estado, "queryConfig": config}
        return {"requestState": estado, "queryConfig": config, **estado}

    @staticmethod
    def _extrair(dados: Any) -> list[dict]:
        """Aceita as formas plausiveis de resposta, nao so a observada.

        Search-UI devolve `{"results": [...]}`; um proxy fino do Elasticsearch
        devolve `{"hits": {"hits": [{"_id", "_source"}]}}`. As duas viram a mesma
        lista de documentos, e `valor()` ja tolera campo cru ou embrulhado.
        """
        if isinstance(dados, list):
            return dados
        if isinstance(dados, dict):
            for chave in ("results", "data", "documents", "items", "orientacoes",
                          "advisees", "content"):
                if isinstance(dados.get(chave), list):
                    return dados[chave]
            hits = dados.get("hits")
            if isinstance(hits, dict) and isinstance(hits.get("hits"), list):
                return [{**(h.get("_source") or {}), "id": h.get("_id")}
                        for h in hits["hits"]]
        if dados in (None, {}):
            return []
        raise ErroDeFonte(
            "resposta fora de qualquer formato conhecido; chaves recebidas: "
            f"{sorted(dados)[:12] if isinstance(dados, dict) else type(dados).__name__}")

    def buscar(self, indice: str, termo: str = "", *, filtros: list[dict] | None = None,
               campos: Sequence[str] = (), busca_em: Sequence[str] = (),
               tamanho: int = 20, pagina: int = 1) -> list[dict]:
        if not termo and not filtros:
            # o servidor responde 400 "Search term or filters are required"; falhar
            # aqui aponta o chamador, que e' onde o defeito de fato esta.
            raise ErroDeFonte(
                f"busca em '{indice}' sem termo e sem filtros — o BrCris exige um dos dois")
        args = (indice, termo, filtros or [], campos, busca_em, tamanho, pagina)
        # o formato ja negociado vem primeiro; na primeira chamada, todos entram
        ordem = ([self.formato] if self.formato else []) + \
                [f for f in self.FORMATOS if f != self.formato]
        erros: list[str] = []
        for formato in ordem:
            try:
                dados = self.post("/api/search", json=self._corpo(formato, *args))
                resultados = self._extrair(dados)
            except ErroDeFonte as err:
                erros.append(f"{formato}: {str(err)[:120]}")
                continue
            if self.formato != formato:
                self.formato = formato
            return resultados
        raise ErroDeFonte(
            "/api/search recusou todos os formatos conhecidos — "
            + " | ".join(erros))

    def por_ids(self, indice: str, ids: Iterable[str], *,
                campos: Sequence[str] = ()) -> list[dict]:
        """Recupera documentos por `_id`, em lotes de 50 (limite do filtro `any`)."""
        ids = [i for i in dict.fromkeys(str(x) for x in ids if x)]
        out: list[dict] = []
        for inicio in range(0, len(ids), LOTE):
            fatia = ids[inicio:inicio + LOTE]
            out.extend(self.buscar(
                indice, filtros=[{"field": "_id", "type": "any", "values": fatia}],
                campos=campos, tamanho=LOTE))
        return out

    # ---- endpoints de lote e de relacao ---- #
    def consulta_autores(self, ids: Sequence[str]) -> list[dict]:
        return self._lote("/api/consulta-autores", ids)

    def consulta_publicacoes(self, ids: Sequence[str]) -> list[dict]:
        return self._lote("/api/consulta-publicacoes", ids)

    def _lote(self, caminho: str, ids: Sequence[str]) -> list[dict]:
        out: list[dict] = []
        ids = [str(i) for i in ids if i]
        for inicio in range(0, len(ids), LOTE):
            out.extend(self._extrair(
                self.post(caminho, json={"ids": ids[inicio:inicio + LOTE]})))
        return out

    def orientacoes(self, advisor_id: str) -> list[dict]:
        # `_extrair` levanta em formato desconhecido em vez de devolver lista vazia:
        # orientacao que some em silencio esvazia a dimensao de formacao do indice.
        return self._extrair(self.get("/api/orientacoes",
                                      params={"advisorId": advisor_id}))

    def coautoria(self, author_id: str) -> Any:
        return self.get("/api/coautoria", params={"authorId": author_id})

    def patentes(self, person_id: str) -> list[dict]:
        return self._extrair(self.get("/api/patent", params={"personId": person_id}))

    def stats(self, indice: str) -> Any:
        return self.get("/api/index-stats", params={"indexesName": self.indice(indice)})


# --------------------------------------------------------------------------- #
# conector
# --------------------------------------------------------------------------- #
CAMPOS_PESSOA = ("id", "name", "lattesId", "orcid", "citationName", "affiliation",
                 "authorOf", "inventorOf", "lastUpdate")
CAMPOS_PUBLICACAO = ("id", "title", "type", "publicationDate", "doi", "journal",
                     "authors", "program", "issn")
CAMPOS_REVISTA = ("id", "title", "issn", "issnL", "evaluationArea")


class ConectorBrCris(Conector):
    nome = "brcris"

    def __init__(self, s, cliente: BrCris | None = None, **kw: Any):
        super().__init__(s, **kw)
        self.api = cliente or BrCris()

    # ------------------------------------------------------------------ #
    # 1. identidade — busca nominal, nunca varredura institucional
    # ------------------------------------------------------------------ #
    def ingerir_docentes(self, nomes: Sequence[str]) -> dict[str, list[str]]:
        """Resolve cada nome da lista da secretaria contra o indice de pessoas.

        Devolve o relatorio de correspondencia. Nome com mais de um candidato
        **nao** e escolhido automaticamente: vai para `ambiguos`, para conferencia
        humana, porque homonimo resolvido no chute contamina todo o indice.
        """
        relatorio: dict[str, list[str]] = {"exatos": [], "ambiguos": [], "sem_match": []}
        for nome in nomes:
            resultados = self.api.buscar(
                "person", nome, campos=CAMPOS_PESSOA, busca_em=("name", "citationName"),
                tamanho=20)
            self.gravar_raw(resultados, ref=f"person/busca/{normalizar_nome(nome)}")

            alvo = normalizar_nome(nome)
            exatos = [r for r in resultados
                      if any(normalizar_nome(str(n)) == alvo
                             for n in lista(r.get("name")) + lista(r.get("citationName")))]
            if len(exatos) != 1:
                (relatorio["ambiguos"] if exatos else relatorio["sem_match"]).append(nome)
                continue

            self._gravar_pessoa(exatos[0], nome)
            relatorio["exatos"].append(nome)

        if not relatorio["exatos"]:
            raise ErroDeFonte("nenhum nome resolvido — verifique o indice e a carga")
        return relatorio

    def _gravar_pessoa(self, doc: dict, nome_lista: str) -> Faculty:
        brcris_id = str(primeiro(doc.get("id")) or "")
        # ID Lattes e TEXT: 0246512416355112 lido como numero perde o zero a esquerda.
        lattes = primeiro(doc.get("lattesId"))
        lattes = str(lattes).strip() if lattes not in (None, "") else None
        orcid = primeiro(doc.get("orcid"))

        pessoa = None
        if lattes:
            pessoa = self.s.scalar(select(Faculty).where(Faculty.lattes_id == lattes))
        if pessoa is None and brcris_id:
            pessoa = self.s.scalar(select(Faculty).where(Faculty.brcris_id == brcris_id))
        if pessoa is None:
            pessoa = Faculty(full_name=nome_lista)
            self.s.add(pessoa)

        pessoa.full_name = str(primeiro(doc.get("name")) or nome_lista)
        pessoa.display_name = nome_lista
        pessoa.lattes_id = lattes or pessoa.lattes_id
        pessoa.orcid = str(orcid) if orcid else pessoa.orcid
        pessoa.brcris_id = brcris_id or pessoa.brcris_id
        self.s.flush()

        for kind, v in (("lattes", lattes), ("orcid", orcid), ("brcris", brcris_id)):
            if not v:
                continue
            ja = self.s.scalar(select(FacultyIdentifier).where(
                FacultyIdentifier.faculty_id == pessoa.id,
                FacultyIdentifier.kind == kind, FacultyIdentifier.value == str(v)))
            if ja is None:
                self.s.add(FacultyIdentifier(faculty_id=pessoa.id, kind=kind,
                                             value=str(v), source=self.nome))

        for assinatura in lista(doc.get("citationName")):
            texto = str(assinatura).strip()
            if not texto:
                continue
            ja = self.s.scalar(select(CitationName).where(
                CitationName.faculty_id == pessoa.id, CitationName.name == texto))
            if ja is None:
                self.s.add(CitationName(faculty_id=pessoa.id, name=texto,
                                        source=self.nome))
        self.s.flush()
        return pessoa

    # ------------------------------------------------------------------ #
    # 2. obras — authorOf -> lote por _id
    # ------------------------------------------------------------------ #
    @staticmethod
    def _item_de_authorof(item: Any) -> dict | None:
        """Normaliza um item de `authorOf`.

        A API devolve **objetos** — `{id, title, title_text, type, publicationDate}` —
        e nao IDs. Tratado como string, o `repr` do dicionario virava o "ID" mandado
        ao lote e a busca por `_id` voltava vazia, sem erro nenhum.

        O objeto ja traz titulo, tipo e data: e' base suficiente para gravar a obra
        mesmo que o lote de publicacoes falhe. Do indice de publicacoes vem o que
        falta aqui — DOI, periodico e ISSN.
        """
        if isinstance(item, dict):
            ref = str(primeiro(item.get("id")) or "").strip()
            return {**item, "id": ref} if ref else None
        ref = str(valor(item) or "").strip()
        return {"id": ref} if ref else None

    def ingerir_obras(self, pessoa: Faculty, *, desempate: str = "menor") -> int:
        if not pessoa.brcris_id:
            return 0
        docs = self.api.por_ids("person", [pessoa.brcris_id], campos=CAMPOS_PESSOA)
        if not docs:
            raise ErroDeFonte(f"pessoa {pessoa.brcris_id} nao retornou documento")
        self.gravar_raw(docs, ref=f"person/{pessoa.brcris_id}")

        embutidas = [x for x in (self._item_de_authorof(i)
                                 for i in lista(docs[0].get("authorOf"))) if x]
        anteriores = len(self.s.scalars(
            select(Authorship).where(Authorship.faculty_id == pessoa.id)).all())
        if not embutidas:
            self.exigir_nao_vazio(embutidas, f"authorOf de {pessoa.full_name}",
                                  anteriores)
            return 0

        ids_obras = [i["id"] for i in embutidas]
        publicacoes = self.api.por_ids("publication", ids_obras,
                                       campos=CAMPOS_PUBLICACAO)
        if not publicacoes:
            # o filtro _id nao trouxe nada: tenta o endpoint de lote antes de
            # desistir do enriquecimento
            publicacoes = self.api.consulta_publicacoes(ids_obras)
        self.gravar_raw(publicacoes, ref=f"publication/de/{pessoa.brcris_id}")

        por_id = {str(primeiro(p.get("id"))): p for p in publicacoes}
        # IDs citados em authorOf que nao retornam documento sao registrados como
        # perda de recuperacao, nao silenciados: na sondagem foram 6 em 1.340.
        faltantes = [i for i in ids_obras if i not in por_id]
        if faltantes:
            self.gravar_raw({"pessoa": pessoa.brcris_id, "nao_recuperados": faltantes},
                            ref=f"publication/faltantes/{pessoa.brcris_id}")

        novas = 0
        for embutida in embutidas:
            # o documento do indice manda no que ele tem; o objeto embutido cobre o
            # resto, e sozinho ja basta para a obra existir
            completa = {**embutida, **por_id.get(embutida["id"], {})}
            obra = self._gravar_obra(completa, desempate=desempate)
            if obra is None:
                continue
            ja = self.s.scalar(select(Authorship).where(
                Authorship.work_id == obra.id, Authorship.faculty_id == pessoa.id))
            if ja is None:
                self.s.add(Authorship(work_id=obra.id, faculty_id=pessoa.id,
                                      fonte=self.nome))
                novas += 1
        self.s.flush()
        return novas

    def _gravar_obra(self, pub: dict, *, desempate: str = "menor") -> Work | None:
        ref = str(primeiro(pub.get("id")) or "")
        titulo = html.unescape(str(primeiro(pub.get("title"))
                                   or primeiro(pub.get("title_text")) or "")).strip()
        if not titulo:
            return None

        anos = anos_de(pub.get("publicationDate"))
        ano = None
        if anos:
            ano = min(anos) if desempate == "menor" else (
                max(anos) if desempate == "maior" else anos[0])

        doi = normalizar_doi(primeiro(pub.get("doi")))
        obra = None
        if doi:
            obra = self.s.scalar(select(Work).where(Work.doi == doi))
        if obra is None and ref:
            obra = self.s.scalar(select(Work).where(
                Work.fonte == self.nome, Work.fonte_ref == ref))
        if obra is None:
            obra = Work(titulo=titulo, fonte=self.nome, fonte_ref=ref)
            self.s.add(obra)

        obra.titulo = titulo
        obra.titulo_normalizado = normalizar_titulo(titulo)
        obra.tipo = classificar(primeiro(pub.get("type")), TIPOS, "outro")
        obra.ano = ano
        obra.data_publicacao_bruta = str(valor(pub.get("publicationDate")))[:200]
        obra.ano_ambiguo = len(anos) > 1
        obra.doi = doi or obra.doi
        obra.resolvido_por = "doi" if doi else (obra.resolvido_por or "nenhum")

        issn = normalizar_issn(primeiro(pub.get("issn")))
        revista = pub.get("journal")
        journal_ref = primeiro(revista.get("id")) if isinstance(revista, dict) else primeiro(revista)
        if issn or journal_ref:
            obra.journal_id = self._gravar_revista(journal_ref, issn,
                                                   primeiro(revista.get("title"))
                                                   if isinstance(revista, dict) else None).id
            obra.issn = issn or obra.issn
        self.s.flush()
        return obra

    def _gravar_revista(self, brcris_id: Any, issn: str | None,
                        titulo: str | None) -> Journal:
        revista = None
        if brcris_id:
            revista = self.s.scalar(select(Journal).where(
                Journal.brcris_id == str(brcris_id)))
        if revista is None and issn:
            revista = self.s.scalar(select(Journal).where(Journal.issn == issn))
        if revista is None:
            revista = Journal(brcris_id=str(brcris_id) if brcris_id else None, issn=issn)
            self.s.add(revista)
        revista.issn = issn or revista.issn
        revista.titulo = titulo or revista.titulo
        self.s.flush()
        return revista

    def enriquecer_revistas(self) -> int:
        """Puxa ISSN e area de avaliacao do indice de revistas.

        E o passo que viabiliza o join com a planilha Qualis: na sondagem, os 114
        periodicos do quadrienio tinham ISSN e 110 tinham area declarada.
        """
        pendentes = self.s.scalars(select(Journal).where(
            Journal.brcris_id.isnot(None), Journal.issn.is_(None))).all()
        if not pendentes:
            return 0
        docs = self.api.por_ids("journal", [j.brcris_id for j in pendentes],
                                campos=CAMPOS_REVISTA)
        self.gravar_raw(docs, ref="journal/lote")
        por_id = {str(primeiro(d.get("id"))): d for d in docs}
        n = 0
        for revista in pendentes:
            doc = por_id.get(str(revista.brcris_id))
            if not doc:
                continue
            revista.issn = normalizar_issn(primeiro(doc.get("issn"))) or revista.issn
            revista.issn_l = normalizar_issn(primeiro(doc.get("issnL"))) or revista.issn_l
            revista.titulo = str(primeiro(doc.get("title")) or revista.titulo or "")
            area = primeiro(doc.get("evaluationArea"))
            revista.area_capes = str(area) if area else revista.area_capes
            n += 1
        self.s.flush()
        return n

    # ------------------------------------------------------------------ #
    # 3. formacao e producao tecnica
    # ------------------------------------------------------------------ #
    def ingerir_orientacoes(self, pessoa: Faculty) -> int:
        if not pessoa.brcris_id:
            return 0
        dados = self.api.orientacoes(pessoa.brcris_id)
        self.gravar_raw(dados, ref=f"orientacoes/{pessoa.brcris_id}")
        anteriores = len(self.s.scalars(select(Orientation).where(
            Orientation.faculty_id == pessoa.id, Orientation.fonte == self.nome)).all())
        self.exigir_nao_vazio(dados, f"orientacoes de {pessoa.full_name}", anteriores)

        n = 0
        for item in dados:
            ref = str(primeiro(item.get("id")) or "")
            ja = self.s.scalar(select(Orientation).where(
                Orientation.faculty_id == pessoa.id, Orientation.fonte == self.nome,
                Orientation.fonte_ref == ref)) if ref else None
            if ja is not None:
                continue
            anos = anos_de(item.get("year") or item.get("date"))
            tipo_txt = " ".join(str(primeiro(item.get(c)) or "")
                                for c in ("type", "level", "title"))
            orientando = str(primeiro(item.get("name")) or
                             primeiro(item.get("advisee")) or "")[:300] or None
            nivel = classificar(tipo_txt, NIVEIS, "nao_informado")
            ano = min(anos) if anos else None
            # a mesma defesa pode ja ter entrado pelo XML do Lattes
            from ..resolve.orientacoes import orientacao_equivalente
            gemea = orientacao_equivalente(self.s, faculty_id=pessoa.id, nivel=nivel,
                                           ano=ano, orientando=orientando)
            if gemea is not None:
                gemea.ano = gemea.ano or ano
                gemea.fonte_ref = gemea.fonte_ref or ref or None
                continue
            self.s.add(Orientation(
                faculty_id=pessoa.id, orientando=orientando, nivel=nivel, ano=ano,
                situacao="concluida", fonte=self.nome, fonte_ref=ref or None))
            n += 1
        self.s.flush()
        return n

    def ingerir_ptt(self, pessoa: Faculty) -> int:
        if not pessoa.brcris_id:
            return 0
        dados = self.api.patentes(pessoa.brcris_id)
        self.gravar_raw(dados, ref=f"patentes/{pessoa.brcris_id}")
        n = 0
        for item in dados:
            ref = str(primeiro(item.get("id")) or "")
            ja = self.s.scalar(select(TechnicalOutput).where(
                TechnicalOutput.faculty_id == pessoa.id,
                TechnicalOutput.fonte == self.nome,
                TechnicalOutput.fonte_ref == ref)) if ref else None
            if ja is not None:
                continue
            anos = anos_de(item.get("date") or item.get("year"))
            self.s.add(TechnicalOutput(
                faculty_id=pessoa.id, tipo="patente",
                titulo=str(primeiro(item.get("title")) or "")[:2000] or None,
                ano=min(anos) if anos else None,
                numero=str(primeiro(item.get("number")) or "")[:80] or None,
                situacao=str(primeiro(item.get("status")) or "")[:30] or None,
                fonte=self.nome, fonte_ref=ref or None))
            n += 1
        self.s.flush()
        return n
