"""BrCris de mentira, no formato Elastic Search-UI observado na sondagem.

Existe porque a API real nao e publica nem documentada: o teste precisa provar a
tubulacao (busca -> authorOf -> lote -> banco) sem depender da rede, e serve de
especificacao executavel do formato que o conector espera receber.
"""

from __future__ import annotations

from typing import Any, Sequence

from obsppg.ingest.brcris import BrCris


def raw(valor: Any) -> dict:
    return {"raw": valor}


PESSOAS = {
    "p-alencar": {
        "id": raw("p-alencar"),
        "name": raw("Ana Ribeiro Alencar"),
        # Pessoas e obras deste arquivo sao ficticias, de proposito: fixture nao
        # carrega registro de pesquisador real. O zero a esquerda e o unico
        # detalhe copiado da realidade — foi observado num ID Lattes de verdade e
        # quebra o identificador se alguem ler a coluna como numero.
        "lattesId": raw("0123456789012345"),
        "orcid": raw("0000-0002-1111-2222"),
        "citationName": raw(["ALENCAR, A. R.", "Alencar, Ana R."]),
        "affiliation": raw([]),
        "authorOf": raw(["w-1", "w-2", "w-3", "w-fantasma"]),
    },
    "p-prado": {
        "id": raw("p-prado"),
        "name": raw("Marcos Vinicius Prado"),
        "lattesId": raw("1234567890123456"),
        "citationName": raw(["PRADO, M. V."]),
        "authorOf": raw(["w-2", "w-4"]),
    },
}

PUBLICACOES = {
    "w-1": {
        "id": raw("w-1"),
        "title": raw("Antifungal activity of native isolates"),
        "type": raw("Journal Article"),
        "publicationDate": raw("2023-05-01"),
        "doi": raw("10.1016/j.mycmed.2023.101"),
        "journal": {"id": raw("j-1"), "title": raw("Journal of Medical Mycology")},
        "program": raw([]),
    },
    "w-2": {
        "id": raw("w-2"),
        "title": raw("Acaros predadores em cultivos do Vale do Taquari"),
        "type": raw("Journal Article"),
        # dois anos no campo: 58 obras do quadrienio tem esse defeito
        "publicationDate": raw(["2021", "2022-03"]),
        "doi": raw(""),
        "journal": {"id": raw("j-2"), "title": raw("Revista Destaques Academicos")},
    },
    "w-3": {
        "id": raw("w-3"),
        "title": raw("Deteccao de dermatofitos em amostras clinicas"),
        "type": raw("Conference Proceedings"),
        "publicationDate": raw("2021"),
    },
    "w-4": {
        "id": raw("w-4"),
        "title": raw("Capitulo sobre acarologia aplicada"),
        "type": raw("Book Chapter"),
        "publicationDate": raw("2024"),
    },
}

REVISTAS = {
    "j-1": {"id": raw("j-1"), "title": raw("Journal of Medical Mycology"),
            "issn": raw("1156-5233"), "evaluationArea": raw("BIOTECNOLOGIA")},
    "j-2": {"id": raw("j-2"), "title": raw("Revista Destaques Academicos"),
            "issn": raw("2176-9257"), "evaluationArea": raw("BIOTECNOLOGIA")},
}

ORIENTACOES = {
    "p-alencar": [
        {"id": "o-1", "name": "Ana Paula Silva", "type": "Mestrado", "year": "2023"},
        {"id": "o-2", "name": "Bruno Costa", "type": "Doutorado", "year": "2024"},
    ],
    "p-prado": [{"id": "o-3", "name": "Carla Souza", "type": "Doutorado", "year": "2022"}],
}

PATENTES = {
    "p-prado": [{"id": "pat-1", "title": "Processo de controle biologico",
                 "date": "2022", "status": "depositada"}],
}


class FakeBrCris(BrCris):
    """Substitui apenas o transporte: a interpretacao testada e a de producao."""

    def __init__(self):
        super().__init__(base="http://exemplo.invalido", carga="nov2025", pausa=0)
        self.chamadas: list[str] = []

    def buscar(self, indice: str, termo: str = "", *, filtros=None, campos=(),
               busca_em=(), tamanho: int = 20, pagina: int = 1) -> list[dict]:
        self.chamadas.append(f"buscar:{indice}:{termo}")
        base = {"person": PESSOAS, "publication": PUBLICACOES, "journal": REVISTAS}
        colecao = next((v for k, v in base.items() if k in indice), {})
        if filtros:
            ids = [str(x) for f in filtros for x in f.get("values", [])]
            return [colecao[i] for i in ids if i in colecao]
        alvo = termo.lower()
        return [d for d in colecao.values()
                if alvo in str(d.get("name", d.get("title", ""))).lower()]

    def orientacoes(self, advisor_id: str) -> list[dict]:
        self.chamadas.append(f"orientacoes:{advisor_id}")
        return ORIENTACOES.get(advisor_id, [])

    def patentes(self, person_id: str) -> list[dict]:
        self.chamadas.append(f"patentes:{person_id}")
        return PATENTES.get(person_id, [])
