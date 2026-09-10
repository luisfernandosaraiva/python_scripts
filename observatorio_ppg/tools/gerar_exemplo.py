#!/usr/bin/env python3
"""Gera `app/data.exemplo.json` a partir das fixtures de teste.

E o estado inicial da interface: pessoas e obras **ficticias**, para que a tela
abra mostrando o que faz antes de qualquer coleta. Assim que
`python -m obsppg export` rodar, `app/data.json` passa a existir e a interface
prefere ele — o exemplo so aparece de novo se o banco for apagado.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from sqlalchemy import select  # noqa: E402

from obsppg.db import criar_schema, sessao  # noqa: E402
from obsppg.ingest.brcris import ConectorBrCris  # noqa: E402
from obsppg.ingest.capes_open import ConectorCAPES  # noqa: E402
from obsppg.ingest.lattes_xml import ConectorLattesXML  # noqa: E402
from obsppg.ingest.qualis import ConectorQualis  # noqa: E402
from obsppg.models import Faculty  # noqa: E402
from obsppg.report.export import exportar  # noqa: E402
from tests.fake_brcris import FakeBrCris  # noqa: E402

FIXTURES = RAIZ / "tests" / "fixtures"


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    banco = tmp / "exemplo.sqlite3"
    criar_schema(banco)

    with sessao(banco) as s:
        brc = ConectorBrCris(s, cliente=FakeBrCris(), raw_dir=tmp / "raw")
        brc.abrir(exemplo=True)
        brc.ingerir_docentes(["Ana Ribeiro Alencar", "Marcos Vinicius Prado"])
        for pessoa in s.scalars(select(Faculty)).all():
            brc.ingerir_obras(pessoa)
            brc.ingerir_orientacoes(pessoa)
            brc.ingerir_ptt(pessoa)
        brc.enriquecer_revistas()
        brc.fechar("ok")

        lat = ConectorLattesXML(s, raw_dir=tmp / "raw")
        lat.abrir(origem="fixture")
        lat.ingerir(FIXTURES / "curriculo_exemplo.xml")
        lat.fechar("ok")

        qua = ConectorQualis(s, raw_dir=tmp / "raw")
        qua.abrir()
        qua.ingerir(FIXTURES / "qualis_exemplo.csv", ciclo="2017-2020")
        qua.fechar("ok")

        cap = ConectorCAPES(s, raw_dir=tmp / "raw")
        cap.abrir()
        cap.ingerir_vinculos(FIXTURES / "capes_exemplo.csv", sigla_ppg="PPGBIOTEC",
                             codigo_capes="42014018003P9")
        cap.fechar("ok")

        destino = RAIZ / "app" / "data.exemplo.json"
        exportar(s, destino, inicio=2021, fim=2024,
                 ciclo_qualis="2017-2020", area_qualis="BIOTECNOLOGIA")

    dados = json.loads(destino.read_text(encoding="utf-8"))
    dados["exemplo"] = True
    dados["aviso"] = ("Dados de demonstracao: pessoas e obras ficticias, geradas das "
                      "fixtures de teste. Rode `python -m obsppg ingest` e "
                      "`python -m obsppg export` para ver o PPG real.")
    destino.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{destino} · {len(dados['pesquisadores'])} pesquisadores de exemplo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
