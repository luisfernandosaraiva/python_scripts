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


class LeituraTolerantesTest(unittest.TestCase):
    """Endpoint que devolve formato inesperado tem de gritar, nao devolver vazio.

    Orientacao que some em silencio esvazia a dimensao de formacao do indice — e o
    erro so apareceria muito depois, ja dentro do IPD.
    """

    def _api(self, resposta):
        class Servidor(BrCris):
            def __init__(self):
                super().__init__(base="http://exemplo.invalido", pausa=0)

            def get(self, caminho, **kwargs):
                return resposta

        return Servidor()

    def test_lista_direta_e_lida(self):
        api = self._api([{"id": "o-1"}, {"id": "o-2"}])
        self.assertEqual(len(api.orientacoes("p-1")), 2)

    def test_lista_embrulhada_em_chave_conhecida(self):
        for chave in ("results", "orientacoes", "advisees", "content", "data"):
            with self.subTest(chave=chave):
                api = self._api({chave: [{"id": "o-1"}]})
                self.assertEqual(len(api.orientacoes("p-1")), 1)

    def test_vazio_legitimo_nao_levanta(self):
        self.assertEqual(self._api([]).orientacoes("p-1"), [])
        self.assertEqual(self._api({}).orientacoes("p-1"), [])

    def test_formato_desconhecido_levanta_nomeando_as_chaves(self):
        api = self._api({"total": 31, "payload": {"lista": [{"id": "o-1"}]}})
        with self.assertRaises(ErroDeFonte) as caso:
            api.orientacoes("p-1")
        self.assertIn("payload", str(caso.exception))
        self.assertIn("total", str(caso.exception))


class BuscaVaziaTest(unittest.TestCase):
    """O 400 da primeira coleta real foi um nome vazio chegando ao servidor."""

    def test_sem_termo_e_sem_filtro_falha_antes_da_rede(self):
        api = BrCris(base="http://exemplo.invalido", pausa=0)
        with self.assertRaises(ErroDeFonte) as caso:
            api.buscar("person", "")
        self.assertIn("sem termo e sem filtros", str(caso.exception))
