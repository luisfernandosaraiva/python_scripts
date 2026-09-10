#!/usr/bin/env bash
# Piloto do PPGBIOTEC, ponta a ponta.
#
#   ./tools/piloto_ppgbiotec.sh
#
# Roda a sequencia validada pela sondagem (§12.5 do documento de decisao). Para
# antes de coletar se alguma fonte estiver fora do contrato, porque coletar com a
# API mudada grava dado incompleto — e dado incompleto no raw contamina o
# recalculo depois.
#
# Os passos que dependem de arquivo que voce baixa (Qualis, CAPES, XML do Lattes)
# rodam se o arquivo existir e sao pulados com aviso se nao existir.

set -euo pipefail
cd "$(dirname "$0")/.."

PPG=PPGBIOTEC
CODIGO=42014018003P9
AREA=BIOTECNOLOGIA
PERIODO=${PERIODO:-2021-2024}
CICLO_QUALIS=${CICLO_QUALIS:-2017-2020}
DOCENTES=${DOCENTES:-docentes_ppgbiotec.txt}
XML_LATTES=${XML_LATTES:-data/raw/lattes}
PLANILHA_QUALIS=${PLANILHA_QUALIS:-data/qualis_${CICLO_QUALIS}.csv}
PLANILHA_CAPES=${PLANILHA_CAPES:-data/capes_docentes.csv}

titulo() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
pulado()  { printf '   \033[2m(pulado) %s\033[0m\n' "$1"; }

titulo "0. Conferindo as fontes antes de tocar no banco"
python3 -m obsppg doctor --nome "$(grep -m1 -v '^\s*#' "$DOCENTES" | tr -d '\r')"

titulo "1. Banco e programa"
python3 -m obsppg init
python3 -m obsppg ppg --sigla "$PPG" --nome "Biotecnologia" \
    --codigo "$CODIGO" --area "$AREA"

titulo "2. Identidade e producao pelo BrCris"
python3 -m obsppg ingest brcris --docentes "$DOCENTES"

titulo "3. Vinculo oficial docente-PPG"
if [ -f "$PLANILHA_CAPES" ]; then
    python3 -m obsppg ingest capes --file "$PLANILHA_CAPES" --ppg "$PPG" --codigo "$CODIGO"
else
    pulado "sem $PLANILHA_CAPES — baixe dos Dados Abertos da CAPES."
    pulado "sem ele, a ficha mostra 'vinculo nao informado' e nao ha categoria."
fi

titulo "4. Estrato Qualis do ciclo"
if [ -f "$PLANILHA_QUALIS" ]; then
    python3 -m obsppg ingest qualis --file "$PLANILHA_QUALIS" \
        --ciclo "$CICLO_QUALIS" --area "$AREA"
else
    pulado "sem $PLANILHA_QUALIS — sem ela a coluna Qualis fica vazia."
fi

titulo "5. Conferencia pelo XML do Lattes"
if [ -d "$XML_LATTES" ] && [ -n "$(ls -A "$XML_LATTES" 2>/dev/null)" ]; then
    python3 -m obsppg ingest lattes --path "$XML_LATTES"
else
    pulado "sem curriculos em $XML_LATTES — as obras sem DOI e sem periodico ficam sem."
fi

titulo "6. Citacoes e coautoria internacional"
python3 -m obsppg ingest openalex

titulo "7. Resolucao e exportacao"
python3 -m obsppg resolve
python3 -m obsppg export --periodo "$PERIODO" \
    --qualis-ciclo "$CICLO_QUALIS" --qualis-area "$AREA"

titulo "Situacao do banco"
python3 -m obsppg status

printf '\nPronto. Abra a interface com:  python3 serve.py\n'
