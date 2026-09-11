# Observatório da Pós-Graduação

Coleta os dados de produção dos docentes de um PPG nas bases públicas disponíveis,
guarda tudo em um banco auditável e apresenta em uma interface centrada no
pesquisador, no padrão do Stela Experta: busca → ficha individual → produção
detalhada, com a procedência de cada número à vista.

O desenho segue o documento de decisão `arquitetura_observatorio_ppg.md`: motor em
Python puro, interface descartável, raw imutável e recálculo determinístico.

```
observatorio_ppg/
├── obsppg/                  motor — nenhuma regra vive fora daqui
│   ├── models.py            schema SQLAlchemy (SQLite no piloto → Postgres sem reescrita)
│   ├── ingest/              um conector por fonte, todos idempotentes
│   ├── resolve/             casamento de obras e de orientações
│   ├── metrics/             indicadores por pesquisador
│   ├── report/export.py     único contrato entre o motor e a tela
│   └── cli.py               ingest | resolve | export | status
├── app/                     interface de leitura (HTML/CSS/JS, sem build)
├── tests/                   suíte offline, com fixtures fictícias
├── tools/gerar_exemplo.py   gera os dados de demonstração da interface
├── dashboard.html           painel do documento de decisão (as medições da sondagem)
└── serve.py                 servidor local das duas telas
```

## Começando

```bash
pip install -r requirements.txt
python3 serve.py                     # http://localhost:8000
```

A interface abre com **dados de demonstração** — pessoas e obras fictícias, geradas
das fixtures de teste, marcadas como tal na própria tela. Nenhum registro de
pesquisador real é distribuído no repositório.

## Piloto do PPGBIOTEC em um comando

A lista nominal dos 11 docentes indicados já está em `docentes_ppgbiotec.txt`
(confira com a secretaria antes de rodar). O bootstrap executa a sequência
validada pela sondagem:

```bash
./tools/piloto_ppgbiotec.sh
```

Ele **confere as fontes antes de tocar no banco** e para se alguma estiver fora do
contrato — coletar com a API mudada grava dado incompleto, e dado incompleto no raw
contamina todo recálculo posterior. Os passos que dependem de arquivo baixado
(Qualis, CAPES, XML do Lattes) rodam se o arquivo existir e avisam quando faltam,
dizendo o que se perde em cada caso.

## Conferindo as fontes

```bash
python -m obsppg doctor
python -m obsppg doctor --nome "Elisete Maria de Freitas"
```

O `doctor` não pergunta só se a API respondeu: confere **campo a campo** se a
resposta traz o que o conector consome (`id`, `name`, `lattesId` são essenciais;
`orcid`, `citationName`, `authorOf` viram aviso). Se o Ibict renomear um campo, a
mensagem diz qual — em vez de o pipeline degradar em silêncio. Sai com código 2
quando alguma fonte falha, então serve em agendador e em CI.

## Coletando passo a passo

A coleta é sempre linha de comando, nunca um botão dentro da interface: assim roda
agendada, com log, e pode ser reexecutada sem duplicar nada.

```bash
python -m obsppg doctor              # as fontes respondem no formato esperado?
python -m obsppg init
python -m obsppg ppg --sigla PPGBIOTEC --nome "Biotecnologia" \
    --codigo 42014018003P9 --area BIOTECNOLOGIA

# 1. identidade + produção, a partir da lista nominal da secretaria
python -m obsppg ingest brcris --docentes docentes.txt

# 2. conferência e o que faltou: XML individual do Lattes (ou do Extrator)
python -m obsppg ingest lattes --path data/raw/lattes/

# 3. vínculo oficial docente↔PPG e categoria
python -m obsppg ingest capes --file docentes_capes_2024.csv --ppg PPGBIOTEC

# 4. estrato Qualis do ciclo, por área
python -m obsppg ingest qualis --file qualis_2017_2020.csv --ciclo 2017-2020 \
    --area BIOTECNOLOGIA

# 5. citações e coautoria internacional, por DOI
python -m obsppg ingest openalex

# 6. resolver duplicatas e exportar para a tela
python -m obsppg resolve
python -m obsppg export --periodo 2021-2024 \
    --qualis-ciclo 2017-2020 --qualis-area BIOTECNOLOGIA
python -m obsppg status
```

`docentes.txt` é um nome por linha. **A lista tem de ser nominal**, da secretaria do
PPG: a sondagem mediu que buscar por nome funciona no BrCris e navegar pela
instituição não — o campo `affiliation` está vazio para os docentes do piloto, e a
varredura institucional devolve um recorte enviesado.

## As fontes e o papel de cada uma

| Fonte | Entra como | Situação |
|---|---|---|
| **BrCris** (`ingest brcris`) | ID Lattes, ORCID, nomes de citação, obras, orientações, patentes | API não documentada; export limitado a 1.000 registros |
| **XML do Lattes** (`ingest lattes`) | conferência: tapa obras sem DOI e valida datas ambíguas | o docente entrega o `.zip`; o mesmo parser serve o Extrator do CNPq |
| **Dados Abertos CAPES** (`ingest capes`) | vínculo docente↔PPG e categoria | planilha pública por coleta |
| **Qualis** (`ingest qualis`) | estrato por ISSN, chaveado por ciclo e área | planilha por ciclo |
| **OpenAlex / Crossref** (`ingest openalex`) | citações, periódico canônico, coautoria estrangeira | API pública; Crossref é a reserva |
| **ORCID** (`ingest orcid`) | DOI declarados pelo próprio autor | API pública |

Duas regras que o código impõe, não sugere:

- **Vínculo com o PPG nunca vem do BrCris.** Só da secretaria ou da CAPES. O campo
  `program` veio vazio em toda a amostra sondada.
- **ID Lattes é texto.** Pode começar com zero; lido como número, o identificador se
  corrompe em silêncio. Há teste para isso.

## O que o banco garante

- **`raw_document` imutável** — todo arquivo e toda resposta ficam gravados como
  vieram, com hash SHA-256 e `sync_run_id`. Recoletar conteúdo idêntico não cria
  linha nova, e o recálculo nunca depende de nova coleta.
- **Falha em vez de sobrescrever com vazio** — se uma fonte devolver nada onde havia
  dados, o `sync_run` termina com status `erro` e o núcleo fica intacto.
- **Nenhum merge sem responsável** — DOI e ISSN+ano+volume+página fundem sozinhos;
  similaridade de título vai para `work_match_decision` com decisão `pendente`,
  esperando revisão humana.
- **`score_component` existe no schema** para quando o índice for definido: cada
  ponto do IPD terá uma linha apontando o item, a regra, a fonte e o documento bruto.

## O que ainda não existe, e por quê

O **cálculo do IPD não está implementado** — e isso é deliberado. A fórmula, os
pesos, a janela e o tratamento de autoria fracionada são decisão pendente do
colegiado (§10 do documento). O motor materializa os insumos; assim que a definição
existir, ela entra como YAML versionado, sem tocar em conector nem em tela.

Também ficam de fora, por dependerem de decisão ou de trâmite: o pedido do Extrator
Lattes (frente administrativa) e a regra de desempate para os campos
`publicationDate` com mais de um ano — hoje o padrão é o menor ano, e a obra fica
marcada como ambígua na ficha.

## O contrato do BrCris, e como o cliente lida com ele

O Ibict não publica nem documenta essa API. O formato do corpo do `/api/search`
observado na sondagem de 09/09/2026 (`requestState`/`queryConfig`) **foi recusado
na primeira coleta real**, com `400 Search term or filters are required` — o
servidor procura `searchTerm` em outro lugar.

Em vez de chutar um formato por vez, o cliente **negocia**: tenta os candidatos
plausíveis em ordem, guarda o que o servidor aceitou e usa só ele daí em diante.
A leitura da resposta é igualmente tolerante — aceita tanto `{"results": [...]}`
do Search-UI quanto `{"hits": {"hits": [...]}}` de um proxy fino do Elasticsearch.
O `doctor` informa qual formato passou; se nenhum passar, ele imprime o que cada
tentativa recebeu de volta.

Na primeira execução real, o formato observado na sondagem passou: o 400 anterior
era o bootstrap mandando um nome vazio, não a API. A negociação ficou como rede de
proteção, com `requestState` — o formato que de fato funciona — sempre em primeiro.

Quando algum endpoint devolver vazio onde deveria ter dado, ou o conector precisar
ser acertado a um formato diferente:

```bash
python -m obsppg doctor --bruto
```

Despeja a resposta crua de cada endpoint que a coleta usa — documento de pessoa,
`/api/orientacoes` (com o `_id` e, se diferente, com o ID Lattes), `/api/patent`,
`consulta-autores`, `consulta-publicacoes` e uma busca por `_id`. Uma execução
mostra o formato de todos eles.

## Testes

```bash
python -m unittest discover -s tests -t .
```

14 testes, sem rede: identidade com zero à esquerda, obra em coautoria interna,
ano ambíguo, raw idempotente, recoleta sem duplicar, XML completando o que faltava,
Qualis e CAPES por chave correta, recusa de sobrescrever com vazio, fila de revisão
humana, dedup de orientação entre fontes (nas duas ordens), exportação, e as três
conferências de contrato do `doctor` (formato completo, campo essencial ausente,
nome sem correspondência).

As fixtures usam pessoas e obras **fictícias** de propósito: fixture de teste não
carrega registro de pesquisador real.

## As duas telas

- `http://localhost:8000/` — **interface do observatório**: busca, ficha do
  pesquisador (indicadores, produção por ano, produção bibliográfica, orientações,
  produção técnica, cobertura e lacunas), visão do programa e procedência dos dados.
- `http://localhost:8000/diagnostico` — **painel do documento de decisão**, com as
  medições da sondagem de 09/09/2026.

O período na barra superior filtra a tela. Quando ele difere do período exportado, a
ficha diz `recalculado na tela` em vez de apresentar o número como oficial.

## LGPD

O cruzamento de dados públicos para produzir um índice individual é tratamento de
dado pessoal com finalidade nova. Antes de publicar qualquer ranking nominal:
registre finalidade, base legal, retenção e quem acessa o quê, e envolva o
encarregado de dados da instituição. Regra defensável: nominal e completo para o
próprio docente e para a coordenação; agregado por PPG para consumo mais amplo.
