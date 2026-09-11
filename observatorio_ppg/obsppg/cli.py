"""Linha de comando do Observatorio.

A coleta e sempre CLI ou agendada — nunca um botao dentro da interface. Cada
comando abre um `sync_run`, grava raw imutavel e sai com codigo != 0 se a fonte
falhar, para que um agendador perceba.

    python -m obsppg doctor
    python -m obsppg init
    python -m obsppg ppg --sigla PPGBIOTEC --nome "Biotecnologia" \
        --codigo 42014018003P9 --area BIOTECNOLOGIA
    python -m obsppg ingest brcris --docentes docentes.txt
    python -m obsppg ingest lattes --path data/raw/lattes/
    python -m obsppg ingest qualis --file qualis_2017_2020.csv --ciclo 2017-2020 \
        --area BIOTECNOLOGIA
    python -m obsppg ingest capes --file docentes_capes_2024.csv --ppg PPGBIOTEC
    python -m obsppg ingest openalex
    python -m obsppg resolve
    python -m obsppg export
    python -m obsppg status
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import func, select

from .config import CONFIG
from .db import criar_schema, sessao
from .ingest.base import ColetaVazia, ErroDeFonte
from .models import PPG, Faculty, Orientation, RawDocument, SyncRun, TechnicalOutput, Work
from .report.export import exportar
from .resolve.works import resolver_obras


def ler_lista(caminho: Path) -> list[str]:
    """Lista nominal da secretaria: um nome por linha, `#` comenta.

    A lista e nominal por decisao medida: buscar por nome funciona no BrCris,
    navegar pela instituicao nao (§12.1).
    """
    nomes = []
    for linha in Path(caminho).read_text(encoding="utf-8").splitlines():
        nome = linha.split("#", 1)[0].strip().strip(";,")
        if nome:
            nomes.append(nome)
    if not nomes:
        raise SystemExit(f"{caminho}: nenhum nome encontrado")
    return nomes


# --------------------------------------------------------------------------- #
def cmd_init(args: argparse.Namespace) -> int:
    CONFIG.preparar()
    criar_schema()
    print(f"banco criado em {CONFIG.banco}")
    return 0


def cmd_ppg(args: argparse.Namespace) -> int:
    with sessao() as s:
        ppg = s.scalar(select(PPG).where(PPG.sigla == args.sigla))
        if ppg is None:
            ppg = PPG(sigla=args.sigla, nome=args.nome or args.sigla)
            s.add(ppg)
        ppg.nome = args.nome or ppg.nome
        ppg.codigo_capes = args.codigo or ppg.codigo_capes
        ppg.area_capes = args.area or ppg.area_capes
        ppg.niveis = args.niveis or ppg.niveis
        print(f"PPG {ppg.sigla}: {ppg.nome} · {ppg.codigo_capes or 's/ codigo'} · "
              f"{ppg.area_capes or 's/ area'}")
    return 0


def cmd_ingest_brcris(args: argparse.Namespace) -> int:
    from .ingest.brcris import ConectorBrCris

    nomes = ler_lista(Path(args.docentes))
    with sessao() as s:
        c = ConectorBrCris(s)
        c.abrir(docentes=len(nomes), carga=c.api.carga)
        try:
            relatorio = c.ingerir_docentes(nomes)
            print(f"identidade: {len(relatorio['exatos'])} exatos, "
                  f"{len(relatorio['ambiguos'])} ambiguos, "
                  f"{len(relatorio['sem_match'])} sem correspondencia")
            for rotulo in ("ambiguos", "sem_match"):
                for nome in relatorio[rotulo]:
                    print(f"  [{rotulo}] {nome}  -> conferir a mao")

            if not args.sem_obras:
                for pessoa in s.scalars(select(Faculty)).all():
                    if not pessoa.brcris_id:
                        continue
                    obras = c.ingerir_obras(pessoa, desempate=args.desempate)
                    orient = c.ingerir_orientacoes(pessoa)
                    ptt = c.ingerir_ptt(pessoa)
                    print(f"  {pessoa.display_name or pessoa.full_name}: "
                          f"{obras} obras, {orient} orientacoes, {ptt} PTT")
                revistas = c.enriquecer_revistas()
                print(f"revistas enriquecidas: {revistas}")
            c.fechar("ok")
        except (ColetaVazia, ErroDeFonte) as err:
            c.fechar("erro", str(err))
            print(f"coleta interrompida: {err}", file=sys.stderr)
            return 2
    return 0


def cmd_ingest_lattes(args: argparse.Namespace) -> int:
    from .ingest.lattes_xml import ConectorLattesXML

    with sessao() as s:
        c = ConectorLattesXML(s)
        c.abrir(origem=str(args.path))
        try:
            totais = c.ingerir(Path(args.path))
            c.fechar("ok")
            print(f"curriculos: {totais['curriculos']} · obras novas: {totais['obras']} "
                  f"· orientacoes: {totais['orientacoes']} · PTT: {totais['ptt']}")
        except (ColetaVazia, FileNotFoundError) as err:
            c.fechar("erro", str(err))
            print(f"coleta interrompida: {err}", file=sys.stderr)
            return 2
    return 0


def cmd_ingest_openalex(args: argparse.Namespace) -> int:
    from .ingest.openalex import ConectorOpenAlex

    with sessao() as s:
        c = ConectorOpenAlex(s)
        c.abrir()
        try:
            n = c.ingerir()
            c.fechar("ok")
            print(f"bibliometria gravada para {n} obra(s)")
        except ErroDeFonte as err:
            c.fechar("erro", str(err))
            print(f"coleta interrompida: {err}", file=sys.stderr)
            return 2
    return 0


def cmd_ingest_orcid(args: argparse.Namespace) -> int:
    from .ingest.orcid import ConectorORCID

    with sessao() as s:
        c = ConectorORCID(s)
        c.abrir()
        try:
            for nome, n in c.ingerir().items():
                print(f"  {nome}: {n} DOI declarados no ORCID")
            c.fechar("ok")
        except ErroDeFonte as err:
            c.fechar("erro", str(err))
            return 2
    return 0


def cmd_ingest_qualis(args: argparse.Namespace) -> int:
    from .ingest.qualis import ConectorQualis

    with sessao() as s:
        c = ConectorQualis(s)
        c.abrir(ciclo=args.ciclo, area=args.area)
        try:
            n = c.ingerir(Path(args.file), ciclo=args.ciclo, area=args.area)
            c.fechar("ok")
            print(f"{n} linhas de Qualis no ciclo {args.ciclo}")
        except ColetaVazia as err:
            c.fechar("erro", str(err))
            print(f"coleta interrompida: {err}", file=sys.stderr)
            return 2
    return 0


def cmd_ingest_capes(args: argparse.Namespace) -> int:
    from .ingest.capes_open import ConectorCAPES

    with sessao() as s:
        c = ConectorCAPES(s)
        c.abrir(ppg=args.ppg)
        try:
            n = c.ingerir_vinculos(Path(args.file), sigla_ppg=args.ppg,
                                   codigo_capes=args.codigo)
            c.fechar("ok")
            print(f"{n} vinculos gravados para {args.ppg}")
        except ColetaVazia as err:
            c.fechar("erro", str(err))
            print(f"coleta interrompida: {err}", file=sys.stderr)
            return 2
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    with sessao() as s:
        resumo = resolver_obras(s, decidido_por=args.por)
        print(f"merges por DOI: {resumo['por_doi']} · por ISSN+ano: {resumo['por_issn']}")
        print(f"pares na fila de revisao humana: {resumo['pendentes_revisao']}")
        print(f"obras nao resolvidas: {resumo['nao_resolvidas']}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    inicio, fim = (int(x) for x in args.periodo.split("-"))
    with sessao() as s:
        destino = exportar(s, Path(args.out) if args.out else None,
                           inicio=inicio, fim=fim,
                           ciclo_qualis=args.qualis_ciclo, area_qualis=args.qualis_area)
    print(f"exportado para {destino}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import bruto, rodar

    return bruto(args.nome) if args.bruto else rodar(args.nome)


def cmd_status(args: argparse.Namespace) -> int:
    if not CONFIG.banco.exists():
        print(f"banco ainda nao existe em {CONFIG.banco} — rode `init`")
        return 1
    with sessao() as s:
        contagens = {
            "pesquisadores": s.scalar(select(func.count(Faculty.id))),
            "obras": s.scalar(select(func.count(Work.id))),
            "obras com DOI": s.scalar(select(func.count(Work.id))
                                      .where(Work.doi.isnot(None))),
            "orientacoes": s.scalar(select(func.count(Orientation.id))),
            "producao tecnica": s.scalar(select(func.count(TechnicalOutput.id))),
            "documentos brutos": s.scalar(select(func.count(RawDocument.id))),
        }
        largura = max(len(k) for k in contagens)
        for chave, valor in contagens.items():
            print(f"  {chave.rjust(largura)} : {valor}")
        print("\n  ultimas coletas")
        for r in s.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(6)).all():
            quando = r.started_at.strftime("%d/%m %H:%M") if r.started_at else "?"
            print(f"    {quando}  {r.source:<12} {r.status:<6} "
                  f"{r.n_documents or 0} doc(s)  {r.error or ''}")
    return 0


# --------------------------------------------------------------------------- #
def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="obsppg", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)

    sub.add_parser("init", help="cria o banco e as pastas").set_defaults(func=cmd_init)

    pp = sub.add_parser("ppg", help="cadastra ou atualiza um programa")
    pp.add_argument("--sigla", required=True)
    pp.add_argument("--nome")
    pp.add_argument("--codigo", help="codigo CAPES, ex. 42014018003P9")
    pp.add_argument("--area", help="area de avaliacao, ex. BIOTECNOLOGIA")
    pp.add_argument("--niveis", help="mestrado, doutorado ou ambos")
    pp.set_defaults(func=cmd_ppg)

    ing = sub.add_parser("ingest", help="coleta de uma fonte")
    fontes = ing.add_subparsers(dest="fonte", required=True)

    b = fontes.add_parser("brcris", help="identidade, obras, orientacoes e patentes")
    b.add_argument("--docentes", required=True, help="arquivo com um nome por linha")
    b.add_argument("--sem-obras", action="store_true",
                   help="so resolve identidade, nao baixa producao")
    b.add_argument("--desempate", choices=("menor", "maior", "primeiro"), default="menor",
                   help="ano a usar quando publicationDate traz mais de um (decisao pendente)")
    b.set_defaults(func=cmd_ingest_brcris)

    l = fontes.add_parser("lattes", help="XML individual ou do Extrator")
    l.add_argument("--path", required=True, help="arquivo .xml, .zip ou diretorio")
    l.set_defaults(func=cmd_ingest_lattes)

    o = fontes.add_parser("openalex", help="citacoes e coautoria por DOI")
    o.set_defaults(func=cmd_ingest_openalex)

    orc = fontes.add_parser("orcid", help="DOI declarados pelo proprio autor")
    orc.set_defaults(func=cmd_ingest_orcid)

    q = fontes.add_parser("qualis", help="planilha de estratos do ciclo")
    q.add_argument("--file", required=True)
    q.add_argument("--ciclo", required=True, help="ex. 2017-2020")
    q.add_argument("--area", help="area de avaliacao, se a planilha nao tiver coluna")
    q.set_defaults(func=cmd_ingest_qualis)

    c = fontes.add_parser("capes", help="vinculo docente-PPG dos dados abertos")
    c.add_argument("--file", required=True)
    c.add_argument("--ppg", required=True)
    c.add_argument("--codigo", help="filtra pelo codigo CAPES do programa")
    c.set_defaults(func=cmd_ingest_capes)

    r = sub.add_parser("resolve", help="casa obras duplicadas e monta a fila de revisao")
    r.add_argument("--por", default="obsppg.resolve", help="quem assina as decisoes")
    r.set_defaults(func=cmd_resolve)

    e = sub.add_parser("export", help="gera o JSON que a interface le")
    e.add_argument("--out")
    e.add_argument("--periodo", default="2021-2024")
    e.add_argument("--qualis-ciclo")
    e.add_argument("--qualis-area")
    e.set_defaults(func=cmd_export)

    d = sub.add_parser("doctor", help="confere se as fontes respondem no contrato esperado")
    d.add_argument("--nome", default="Noeli Juarez Ferla",
                   help="nome usado na busca de prova contra o BrCris")
    d.add_argument("--bruto", action="store_true",
                   help="despeja as respostas cruas dos endpoints, para ajustar o conector")
    d.set_defaults(func=cmd_doctor)

    sub.add_parser("status", help="o que ja entrou no banco").set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    CONFIG.preparar()
    if args.comando != "init":
        criar_schema()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
