"""Conferencia de fontes antes de coletar.

Existe por um motivo concreto: a API do BrCris nao e' publicada nem documentada
pelo Ibict, entao o conector foi escrito contra o formato observado na sondagem
de 09/09/2026. Se o site mudar, o melhor momento para descobrir e' antes da
coleta, com uma mensagem que diga *o que* mudou — e nao no meio do pipeline.

    python -m obsppg doctor
    python -m obsppg doctor --nome "Noeli Juarez Ferla"
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from .config import CONFIG
from .ingest.base import ClienteHTTP, ErroDeFonte
from .ingest.brcris import (
    BrCris,
    CAMPOS_PESSOA,
    CAMPOS_PUBLICACAO,
    ConectorBrCris,
    lista,
    primeiro,
)

OK, FALHA, ALERTA = "  ok  ", " falha", "aviso "

# Campos que o conector consome. Se algum sumir, o pipeline degrada em silencio —
# por isso a conferencia e' campo a campo, e nao so "a API respondeu".
ESSENCIAIS = ("id", "name", "lattesId")
DESEJAVEIS = ("orcid", "citationName", "authorOf")


def _amostra(rotulo: str, obter: Callable[[], Any], limite: int = 1400) -> None:
    """Imprime a resposta crua de uma chamada, para acertar o conector de uma vez."""
    import json

    print(f"\n--- {rotulo} ---")
    try:
        dados = obter()
    except Exception as err:
        print(f"  falhou: {type(err).__name__}: {str(err)[:300]}")
        return
    texto = json.dumps(dados, ensure_ascii=False, indent=1)[:limite]
    print(texto + ("\n  [...cortado]" if len(texto) >= limite else ""))


def bruto(nome: str, api: BrCris | None = None) -> int:
    """Despeja as respostas cruas dos endpoints que a coleta usa.

    Serve para dois casos: quando um endpoint devolve vazio onde deveria ter dado
    (e' preciso ver *o que* ele devolveu), e quando o conector precisa ser ajustado
    a um formato diferente do observado.
    """
    api = api or BrCris()
    resultados = api.buscar("person", nome, campos=CAMPOS_PESSOA,
                            busca_em=("name", "citationName"), tamanho=3)
    if not resultados:
        print(f"'{nome}' nao retornou ninguem no indice de pessoas.", file=sys.stderr)
        return 2

    doc = resultados[0]
    pessoa_id = str(primeiro(doc.get("id")) or "")
    lattes = str(primeiro(doc.get("lattesId")) or "")
    # authorOf traz objetos, nao IDs — o mesmo engano que quebrou o conector
    itens = [ConectorBrCris._item_de_authorof(i) for i in lista(doc.get("authorOf"))]
    obras = [i["id"] for i in itens if i][:3]

    print(f"formato do corpo aceito: {api.formato}")
    _amostra("documento de pessoa (primeiro resultado)", lambda: doc, limite=2200)
    _amostra(f"/api/orientacoes?advisorId={pessoa_id}",
             lambda: api.get("/api/orientacoes", params={"advisorId": pessoa_id}))
    if lattes and lattes != pessoa_id:
        # hipotese: o endpoint pode esperar o ID Lattes, nao o _id do indice
        _amostra(f"/api/orientacoes?advisorId={lattes} (tentativa com ID Lattes)",
                 lambda: api.get("/api/orientacoes", params={"advisorId": lattes}))
    _amostra(f"/api/patent?personId={pessoa_id}",
             lambda: api.get("/api/patent", params={"personId": pessoa_id}))
    _amostra(f"/api/consulta-autores (ids=[{pessoa_id}])",
             lambda: api.post("/api/consulta-autores", json={"ids": [pessoa_id]}))
    if obras:
        _amostra(f"/api/consulta-publicacoes (ids={obras})",
                 lambda: api.post("/api/consulta-publicacoes", json={"ids": obras}))
        _amostra("uma publicacao pelo /api/search com filtro _id",
                 lambda: api.buscar("publication",
                                    filtros=[{"field": "_id", "type": "any",
                                              "values": obras[:1]}],
                                    campos=CAMPOS_PUBLICACAO, tamanho=1))
    return 0


class Resultado:
    def __init__(self, fonte: str, estado: str, detalhe: str):
        self.fonte, self.estado, self.detalhe = fonte, estado, detalhe

    def imprimir(self) -> None:
        import shutil
        import textwrap

        largura = max(60, min(shutil.get_terminal_size((100, 24)).columns, 110))
        recuo = " " * 33
        linhas = textwrap.wrap(self.detalhe, width=largura - 33) or [""]
        print(f"  [{self.estado}] {self.fonte:<22} {linhas[0]}")
        for linha in linhas[1:]:
            print(f"{recuo}{linha}")


def _tentar(fonte: str, funcao: Callable[[], tuple[str, str]]) -> Resultado:
    try:
        estado, detalhe = funcao()
    except ErroDeFonte as err:
        return Resultado(fonte, FALHA, str(err))
    except Exception as err:  # rede, DNS, TLS
        return Resultado(fonte, FALHA, f"{type(err).__name__}: {str(err)[:130]}")
    return Resultado(fonte, estado, detalhe)


# --------------------------------------------------------------------------- #
def checar_brcris(nome: str, api: BrCris | None = None) -> tuple[str, str]:
    api = api or BrCris()
    stats = api.stats("person")
    resultados = api.buscar("person", nome, campos=CAMPOS_PESSOA,
                            busca_em=("name", "citationName"), tamanho=5)
    if not resultados:
        return ALERTA, (f"indice responde, mas '{nome}' nao retornou ninguem — "
                        "confira a grafia ou a carga do indice")

    doc = resultados[0]
    faltando = [c for c in ESSENCIAIS if primeiro(doc.get(c)) in (None, "")]
    ausentes = [c for c in DESEJAVEIS if not lista(doc.get(c))]
    total = ""
    if isinstance(stats, dict):
        for chave in ("count", "docsCount", "total"):
            if chave in stats:
                total = f"{stats[chave]} docs · "
                break

    if faltando:
        return FALHA, (f"{total}resposta sem {', '.join(faltando)} — o contrato do "
                       "conector mudou; ajuste obsppg/ingest/brcris.py")
    obras = len(lista(doc.get("authorOf")))
    formato = f" · formato do corpo: {api.formato}" if api.formato else ""
    recado = f"{total}'{nome}' resolvido · lattesId ok · {obras} obras em authorOf{formato}"
    if ausentes:
        recado += f" · sem {', '.join(ausentes)}"

    # /api/orientacoes e' a dimensao de formacao do indice. Conferir agora sai de
    # graca — ja temos um person_id resolvido — e evita descobrir no meio da coleta.
    pessoa_id = str(primeiro(doc.get("id")) or "")
    try:
        orientandos = api.orientacoes(pessoa_id)
    except ErroDeFonte as err:
        return ALERTA, (recado + f" · /api/orientacoes falhou ({str(err)[:80]}): "
                        "a dimensao de formacao ficaria vazia")
    recado += f" · {len(orientandos)} orientandos em /api/orientacoes"
    if obras and not orientandos:
        return ALERTA, (recado + " — zero orientandos em quem tem producao e' suspeito; "
                        "rode `python -m obsppg doctor --bruto` para ver a resposta crua")
    return (ALERTA if ausentes else OK), recado


def checar_openalex() -> tuple[str, str]:
    params: dict[str, Any] = {"per-page": 1}
    if CONFIG.contato:
        params["mailto"] = CONFIG.contato
    dados = ClienteHTTP(CONFIG.openalex_base).get("/works", params=params)
    n = (dados.get("meta") or {}).get("count")
    aviso = "" if CONFIG.contato else " · defina OBSPPG_CONTATO para o polite pool"
    return OK, f"{n:,} obras indexadas{aviso}".replace(",", ".")


def checar_crossref() -> tuple[str, str]:
    dados = ClienteHTTP(CONFIG.crossref_base).get("/works/10.1038/nature12373")
    titulo = (dados.get("message") or {}).get("title") or [""]
    return OK, f"DOI de teste resolvido: {titulo[0][:60]}"


def checar_orcid() -> tuple[str, str]:
    # ORCID publico de teste mantido pelo proprio ORCID (Josiah Carberry, ficticio)
    dados = ClienteHTTP(CONFIG.orcid_base).get("/0000-0002-1825-0097/record")
    nome = ((dados.get("person") or {}).get("name") or {})
    dado = (nome.get("given-names") or {}).get("value", "?")
    return OK, f"registro publico de teste lido ({dado})"


def rodar(nome: str = "Noeli Juarez Ferla", api: BrCris | None = None) -> int:
    print(f"Conferindo fontes · carga BrCris '{CONFIG.brcris_carga}'\n")
    resultados = [
        _tentar("BrCris", lambda: checar_brcris(nome, api)),
        _tentar("OpenAlex", checar_openalex),
        _tentar("Crossref", checar_crossref),
        _tentar("ORCID", checar_orcid),
    ]
    for r in resultados:
        r.imprimir()

    print("\n  as duas fontes de arquivo local nao dependem de rede:")
    print("    CAPES  planilha de dados abertos -> ingest capes --file ...")
    print("    Qualis planilha do ciclo         -> ingest qualis --file ...")

    falhas = [r for r in resultados if r.estado == FALHA]
    if falhas:
        print(f"\n{len(falhas)} fonte(s) fora do ar ou fora do contrato. "
              "Coletar agora grava dado incompleto.", file=sys.stderr)
        return 2
    if any(r.estado == ALERTA for r in resultados):
        print("\nDa para coletar, mas leia os avisos acima antes.")
    else:
        print("\nTudo no contrato esperado. Pode coletar.")
    return 0
