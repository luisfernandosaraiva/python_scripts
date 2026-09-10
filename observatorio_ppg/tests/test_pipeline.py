"""Teste de ponta a ponta do motor, sem rede.

Cobre o caminho que o piloto vai percorrer de verdade: identidade pelo BrCris,
obras por `authorOf`, orientacoes e PTT, conferencia pelo XML do Lattes, Qualis
por ISSN, vinculo pela CAPES, resolucao de duplicatas e exportacao para a tela.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from sqlalchemy import select

from obsppg.db import criar_schema, sessao
from obsppg.ingest.base import ColetaVazia
from obsppg.ingest.brcris import ConectorBrCris, normalizar_doi, normalizar_issn
from obsppg.ingest.capes_open import ConectorCAPES
from obsppg.ingest.lattes_xml import ConectorLattesXML
from obsppg.ingest.qualis import ConectorQualis
from obsppg.metrics.indicadores import indicadores_do_pesquisador, producao_por_ano
from obsppg.models import Authorship, Faculty, Orientation, RawDocument, Work
from obsppg.report.export import exportar
from obsppg.resolve.works import resolver_obras
from tests.fake_brcris import FakeBrCris

FIXTURES = Path(__file__).parent / "fixtures"


class PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.banco = self.tmp / "teste.sqlite3"
        criar_schema(self.banco)

    def _coletar_brcris(self, s):
        c = ConectorBrCris(s, cliente=FakeBrCris(), raw_dir=self.tmp / "raw")
        c.abrir(teste=True)
        relatorio = c.ingerir_docentes(["Ana Ribeiro Alencar", "Marcos Vinicius Prado"])
        for pessoa in s.scalars(select(Faculty)).all():
            c.ingerir_obras(pessoa)
            c.ingerir_orientacoes(pessoa)
            c.ingerir_ptt(pessoa)
        c.enriquecer_revistas()
        c.fechar("ok")
        return c, relatorio

    # ------------------------------------------------------------------ #
    def test_identidade_preserva_zero_a_esquerda(self):
        with sessao(self.banco) as s:
            _, relatorio = self._coletar_brcris(s)
            self.assertEqual(relatorio["exatos"],
                             ["Ana Ribeiro Alencar", "Marcos Vinicius Prado"])
            pessoa = s.scalar(select(Faculty).where(
                Faculty.full_name == "Ana Ribeiro Alencar"))
            self.assertEqual(pessoa.lattes_id, "0123456789012345")
            self.assertIsInstance(pessoa.lattes_id, str)
            self.assertIn("ALENCAR, A. R.", [c.name for c in pessoa.citation_names])

    def test_obra_compartilhada_gera_duas_autorias_e_uma_obra(self):
        with sessao(self.banco) as s:
            self._coletar_brcris(s)
            obra = s.scalar(select(Work).where(Work.fonte_ref == "w-2"))
            autorias = s.scalars(select(Authorship).where(
                Authorship.work_id == obra.id)).all()
            self.assertEqual(len(autorias), 2, "obra de dois docentes nao pode duplicar")

    def test_ano_ambiguo_e_marcado_e_desempatado(self):
        with sessao(self.banco) as s:
            self._coletar_brcris(s)
            obra = s.scalar(select(Work).where(Work.fonte_ref == "w-2"))
            self.assertTrue(obra.ano_ambiguo)
            self.assertEqual(obra.ano, 2021)  # desempate padrao: menor

    def test_raw_imutavel_e_idempotente(self):
        with sessao(self.banco) as s:
            self._coletar_brcris(s)
            antes = len(s.scalars(select(RawDocument)).all())
        with sessao(self.banco) as s:
            self._coletar_brcris(s)
            depois = len(s.scalars(select(RawDocument)).all())
        self.assertEqual(antes, depois, "recoleta identica nao pode criar raw novo")

    def test_recoleta_nao_duplica_obras(self):
        with sessao(self.banco) as s:
            self._coletar_brcris(s)
            n1 = len(s.scalars(select(Work)).all())
        with sessao(self.banco) as s:
            self._coletar_brcris(s)
            n2 = len(s.scalars(select(Work)).all())
        self.assertEqual(n1, n2)

    def test_lattes_xml_completa_o_que_faltava(self):
        with sessao(self.banco) as s:
            self._coletar_brcris(s)
            c = ConectorLattesXML(s, raw_dir=self.tmp / "raw")
            c.abrir(origem="fixture")
            totais = c.ingerir(FIXTURES / "curriculo_exemplo.xml")
            c.fechar("ok")
            self.assertEqual(totais["curriculos"], 1)

            # a obra ja existia pelo BrCris (mesmo DOI) — o XML nao pode duplicar
            iguais = s.scalars(select(Work).where(
                Work.doi == "10.1016/j.mycmed.2023.101")).all()
            self.assertEqual(len(iguais), 1)
            self.assertEqual(iguais[0].issn, "1156-5233",
                             "ISSN deveria ter vindo do XML")

            pessoa = s.scalar(select(Faculty).where(
                Faculty.lattes_id == "0123456789012345"))
            niveis = {o.nivel for o in s.scalars(select(Orientation).where(
                Orientation.faculty_id == pessoa.id)).all()}
            self.assertEqual(niveis, {"mestrado", "doutorado"})
            coorientacao = s.scalars(select(Orientation).where(
                Orientation.faculty_id == pessoa.id,
                Orientation.papel == "coorientacao")).all()
            self.assertEqual(len(coorientacao), 1)

    def test_qualis_e_capes_entram_por_chave_correta(self):
        with sessao(self.banco) as s:
            self._coletar_brcris(s)
            q = ConectorQualis(s, raw_dir=self.tmp / "raw")
            q.abrir()
            n = q.ingerir(FIXTURES / "qualis_exemplo.csv", ciclo="2017-2020")
            q.fechar("ok")
            self.assertEqual(n, 3)

            from obsppg.metrics.indicadores import estrato_por_issn
            tabela = estrato_por_issn(s, ciclo="2017-2020", area="BIOTECNOLOGIA")
            self.assertEqual(tabela["1156-5233"], "A2")
            self.assertNotIn("0001-0001", tabela, "area errada nao pode vazar")

            c = ConectorCAPES(s, raw_dir=self.tmp / "raw")
            c.abrir()
            n = c.ingerir_vinculos(FIXTURES / "capes_exemplo.csv",
                                   sigla_ppg="PPGBIOTEC", codigo_capes="42014018003P9")
            c.fechar("ok")
            self.assertEqual(n, 2, "so os vinculos do codigo pedido")

    def test_falha_em_vez_de_sobrescrever_com_vazio(self):
        with sessao(self.banco) as s:
            c, _ = self._coletar_brcris(s)
            pessoa = s.scalar(select(Faculty).where(Faculty.brcris_id == "p-alencar"))
            c.api.orientacoes = lambda _: []          # a fonte "esqueceu" os dados
            with self.assertRaises(ColetaVazia):
                c.ingerir_orientacoes(pessoa)
            restantes = s.scalars(select(Orientation).where(
                Orientation.faculty_id == pessoa.id)).all()
            self.assertTrue(restantes, "o nucleo tem de ficar intacto")

    def test_resolucao_manda_duvida_para_revisao_humana(self):
        with sessao(self.banco) as s:
            self._coletar_brcris(s)
            # duplicata plausivel, sem DOI: tem de virar pendencia, nao merge
            s.add(Work(titulo="Deteccao de dermatofitos em amostras clinicas.",
                       titulo_normalizado="deteccao de dermatofitos em amostras clinicas",
                       tipo="evento", ano=2021, fonte="manual", fonte_ref="dup"))
            s.flush()
            resumo = resolver_obras(s)
            self.assertGreaterEqual(resumo["pendentes_revisao"], 1)
            self.assertEqual(resumo["por_doi"], 0)

    def test_indicadores_e_export(self):
        with sessao(self.banco) as s:
            self._coletar_brcris(s)
            pessoa = s.scalar(select(Faculty).where(Faculty.brcris_id == "p-alencar"))
            ind = indicadores_do_pesquisador(s, pessoa, inicio=2021, fim=2024)
            self.assertEqual(ind["obras_periodo"], 3)
            self.assertEqual(ind["artigos_total"], 2)
            self.assertEqual(ind["orientacoes"], 2)
            self.assertEqual(ind["pct_doi_periodo"], 33.3)

            serie = producao_por_ano([w for w in s.scalars(select(Work)).all()])
            self.assertEqual([p["ano"] for p in serie], [2021, 2023, 2024])

            destino = exportar(s, self.tmp / "data.json", inicio=2021, fim=2024,
                               ciclo_qualis="2017-2020", area_qualis="BIOTECNOLOGIA")
            dados = json.loads(destino.read_text(encoding="utf-8"))
            self.assertEqual(len(dados["pesquisadores"]), 2)
            alencar = next(p for p in dados["pesquisadores"]
                            if p["lattes_id"] == "0123456789012345")
            self.assertEqual(alencar["indicadores"]["obras_periodo"], 3)
            self.assertTrue(any(o["ano_ambiguo"] for p in dados["pesquisadores"]
                                for o in p["obras"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class OrientacaoDuplicadaTest(unittest.TestCase):
    """A mesma defesa vinda de duas fontes tem de virar uma linha so."""

    def setUp(self) -> None:
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.banco = self.tmp / "orient.sqlite3"
        criar_schema(self.banco)

    def _pipeline(self, s, primeiro_lattes: bool):
        def brcris():
            c = ConectorBrCris(s, cliente=FakeBrCris(), raw_dir=self.tmp / "raw")
            c.abrir()
            c.ingerir_docentes(["Ana Ribeiro Alencar"])
            for pessoa in s.scalars(select(Faculty)).all():
                c.ingerir_orientacoes(pessoa)
            c.fechar("ok")

        def lattes():
            c = ConectorLattesXML(s, raw_dir=self.tmp / "raw")
            c.abrir()
            c.ingerir(FIXTURES / "curriculo_exemplo.xml")
            c.fechar("ok")

        (lattes(), brcris()) if primeiro_lattes else (brcris(), lattes())

    def test_dedup_independe_da_ordem_das_fontes(self):
        for primeiro_lattes in (False, True):
            with self.subTest(lattes_primeiro=primeiro_lattes):
                banco = self.tmp / f"ord-{primeiro_lattes}.sqlite3"
                criar_schema(banco)
                with sessao(banco) as s:
                    self._pipeline(s, primeiro_lattes)
                    pessoa = s.scalar(select(Faculty).where(
                        Faculty.lattes_id == "0123456789012345"))
                    orientacoes = s.scalars(select(Orientation).where(
                        Orientation.faculty_id == pessoa.id)).all()
                    self.assertEqual(len(orientacoes), 2,
                                     "duas fontes, dois orientandos, duas linhas")
                    self.assertEqual(
                        {o.nivel for o in orientacoes}, {"mestrado", "doutorado"})
                    coorientacao = [o for o in orientacoes if o.papel == "coorientacao"]
                    self.assertEqual(len(coorientacao), 1,
                                     "o papel do XML nao pode se perder no merge")


class DoctorTest(unittest.TestCase):
    """A conferencia de contrato tem de acusar campo que sumiu da API.

    O conector do BrCris foi escrito contra um formato observado, nao publicado.
    Se o Ibict renomear `lattesId`, o pipeline degradaria em silencio — estes
    testes garantem que o `doctor` acusa antes da coleta.
    """

    def test_contrato_completo_passa(self):
        from obsppg.doctor import OK, checar_brcris

        estado, detalhe = checar_brcris("Ana Ribeiro Alencar", FakeBrCris())
        self.assertEqual(estado, OK)
        self.assertIn("lattesId ok", detalhe)
        self.assertIn("4 obras", detalhe)

    def test_campo_essencial_ausente_vira_falha(self):
        from obsppg.doctor import FALHA, checar_brcris

        api = FakeBrCris()
        original = api.buscar

        def sem_lattes(*a, **kw):
            docs = [dict(d) for d in original(*a, **kw)]
            for doc in docs:
                doc.pop("lattesId", None)
            return docs

        api.buscar = sem_lattes
        estado, detalhe = checar_brcris("Ana Ribeiro Alencar", api)
        self.assertEqual(estado, FALHA)
        self.assertIn("lattesId", detalhe)
        self.assertIn("brcris.py", detalhe)

    def test_nome_sem_correspondencia_vira_aviso(self):
        from obsppg.doctor import ALERTA, checar_brcris

        estado, detalhe = checar_brcris("Pessoa Que Nao Existe", FakeBrCris())
        self.assertEqual(estado, ALERTA)
        self.assertIn("nao retornou ninguem", detalhe)
