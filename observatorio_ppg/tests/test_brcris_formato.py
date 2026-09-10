"""Negociacao do formato do /api/search.

A primeira coleta real recebeu `400 Search term or filters are required`, o que
significa que o servidor procura `searchTerm` em outro lugar do corpo. Estes
testes simulam servidores que aceitam cada um dos formatos plausiveis e provam
que o cliente encontra o certo sozinho — e que, uma vez encontrado, nao fica
tentando os outros a cada chamada.

Aqui o falso substitui apenas o transporte HTTP (`post`), entao o codigo sob
teste e' exatamente o que vai conversar com o BrCris.
"""

from __future__ import annotations

import unittest

from obsppg.ingest.base import ErroDeFonte
from obsppg.ingest.brcris import BrCris

DOC = {"id": {"raw": "p-1"}, "name": {"raw": "Fulana de Tal"},
       "lattesId": {"raw": "0123456789012345"}}


class ServidorFalso(BrCris):
    """Aceita so um formato de corpo; responde 400 como o BrCris real fez."""

    def __init__(self, aceita: str, *, resposta: str = "results"):
        super().__init__(base="http://exemplo.invalido", carga="nov2025", pausa=0)
        self.aceita, self.resposta = aceita, resposta
        self.tentativas: list[str] = []

    def post(self, caminho, **kwargs):
        corpo = kwargs.get("json") or {}
        self.tentativas.append(self._nomear(corpo))
        termo = self._termo(corpo)
        if self._nomear(corpo) != self.aceita or not termo:
            raise ErroDeFonte('400 em /api/search: '
                              '{"error":"Search term or filters are required"}')
        if self.resposta == "hits":
            return {"hits": {"hits": [{"_id": "p-1",
                                       "_source": {"name": "Fulana de Tal",
                                                   "lattesId": "0123456789012345"}}]}}
        return {"results": [DOC]}

    @staticmethod
    def _nomear(corpo: dict) -> str:
        if "state" in corpo and "requestState" not in corpo:
            return "state"
        if "requestState" in corpo:
            return "misto" if "searchTerm" in corpo else "requestState"
        return "plano"

    @staticmethod
    def _termo(corpo: dict):
        for lugar in (corpo, corpo.get("requestState") or {}, corpo.get("state") or {}):
            if isinstance(lugar, dict) and lugar.get("searchTerm"):
                return lugar["searchTerm"]
        return None


class NegociacaoTest(unittest.TestCase):
    def test_encontra_qualquer_formato_aceito(self):
        for formato in BrCris.FORMATOS:
            with self.subTest(formato=formato):
                api = ServidorFalso(formato)
                resultados = api.buscar("person", "Fulana de Tal", campos=("id", "name"),
                                        busca_em=("name",))
                self.assertEqual(len(resultados), 1)
                self.assertEqual(api.formato, formato)

    def test_nao_renegocia_depois_de_achar(self):
        api = ServidorFalso("plano")
        api.buscar("person", "Fulana de Tal")
        gastas = len(api.tentativas)
        api.buscar("person", "Outra Pessoa")
        self.assertEqual(len(api.tentativas) - gastas, 1,
                         "a segunda busca deve ir direto ao formato ja negociado")

    def test_resposta_do_elasticsearch_cru_tambem_serve(self):
        api = ServidorFalso("plano", resposta="hits")
        resultados = api.buscar("person", "Fulana de Tal")
        self.assertEqual(len(resultados), 1)
        # `_source` vem sem o embrulho {"raw": ...}; os leitores toleram os dois
        from obsppg.ingest.brcris import primeiro
        self.assertEqual(primeiro(resultados[0]["lattesId"]), "0123456789012345")
        self.assertEqual(primeiro(resultados[0]["id"]), "p-1")

    def test_todos_recusados_diz_o_que_cada_um_respondeu(self):
        api = ServidorFalso("nenhum")
        with self.assertRaises(ErroDeFonte) as caso:
            api.buscar("person", "Fulana de Tal")
        recado = str(caso.exception)
        self.assertIn("recusou todos os formatos", recado)
        for formato in BrCris.FORMATOS:
            self.assertIn(formato, recado)


if __name__ == "__main__":
    unittest.main(verbosity=2)
