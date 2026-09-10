/* Observatorio PPG — casca de leitura.
 *
 * Regra de arquitetura: nenhuma regra de indice vive aqui. Este arquivo le o JSON
 * que `python -m obsppg export` produziu e desenha. Filtrar por periodo e contar o
 * que aparece na tela e apresentacao; converter producao em pontos e' motor, e mora
 * em `obsppg/`. Quando o periodo da tela difere do periodo exportado, a interface
 * diz isso em vez de fingir que o numero e o oficial.
 */
"use strict";

const TIPOS = [
  ["artigo", "Artigos", "--s1"],
  ["evento", "Trabalhos em eventos", "--s2"],
  ["capitulo", "Capítulos", "--s3"],
  ["preprint", "Preprints", "--s4"],
  ["livro", "Livros", "--s5"],
  ["tese", "Teses e dissertações", "--s6"],
  ["outro", "Outros", "--neutro"],
];
const COR = Object.fromEntries(TIPOS.map(([k, , v]) => [k, `var(${v})`]));
const ROTULO = Object.fromEntries(TIPOS.map(([k, r]) => [k, r]));
const NIVEL = {
  mestrado: "Mestrado", doutorado: "Doutorado", pos_doutorado: "Pós-doutorado",
  iniciacao: "Iniciação científica", nao_informado: "Não informado",
};

const estado = {
  dados: null, exemplo: false, pessoa: null, visao: "pesquisador",
  aba: "producao", busca: "", ppg: "", inicio: 2021, fim: 2024,
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, props = {}, filhos = []) => {
  // `dataset` e `style` sao somente-leitura: Object.assign neles lanca TypeError.
  const { dataset, ...resto } = props;
  const node = Object.assign(document.createElement(tag), resto);
  if (dataset) {
    for (const [chave, valor] of Object.entries(dataset)) node.dataset[chave] = valor;
  }
  for (const filho of [].concat(filhos)) {
    if (filho != null) node.append(filho);
  }
  return node;
};
const num = (n) => (n == null ? "—" : new Intl.NumberFormat("pt-BR").format(n));
const pct = (n) => (n == null ? "—" : `${n.toFixed(1).replace(".", ",")}%`);

/* ------------------------------------------------------------------ tooltip */
const tip = $("#tip");
document.addEventListener("pointermove", (e) => {
  const alvo = e.target.closest?.("[data-tip]");
  if (!alvo) { tip.style.opacity = "0"; return; }
  tip.innerHTML = alvo.getAttribute("data-tip");
  tip.style.opacity = "1";
  const r = tip.getBoundingClientRect();
  tip.style.left = `${Math.min(Math.max(8, e.clientX + 14), innerWidth - r.width - 8)}px`;
  const acima = e.clientY - r.height - 12;
  tip.style.top = `${acima < 8 ? e.clientY + 18 : acima}px`;
});

/* ------------------------------------------------------------------- dados */
async function carregar() {
  for (const [arquivo, ehExemplo] of [["data.json", false], ["data.exemplo.json", true]]) {
    try {
      const resp = await fetch(arquivo, { cache: "no-store" });
      if (!resp.ok) continue;
      const dados = await resp.json();
      return { dados, exemplo: ehExemplo || dados.exemplo === true };
    } catch (err) { /* tenta o proximo */ }
  }
  return null;
}

function noPeriodo(obras) {
  return obras.filter((o) => o.ano != null && o.ano >= estado.inicio && o.ano <= estado.fim);
}

/** Indicadores da janela mostrada na tela. Quando ela coincide com a exportada,
 *  os numeros sao os mesmos que o motor gravou — a tela so os repete. */
function indicadoresDaTela(pessoa) {
  const janela = noPeriodo(pessoa.obras);
  const artigos = janela.filter((o) => o.tipo === "artigo");
  const comDoi = janela.filter((o) => o.doi);
  const orient = pessoa.orientacoes.filter(
    (o) => o.ano == null || (o.ano >= estado.inicio && o.ano <= estado.fim));
  const tec = pessoa.tecnica.filter(
    (t) => t.ano == null || (t.ano >= estado.inicio && t.ano <= estado.fim));
  const citacoes = janela.reduce((soma, o) => soma + (o.citacoes || 0), 0);
  return {
    obras: janela.length,
    artigos: artigos.length,
    pctDoi: janela.length ? (comDoi.length / janela.length) * 100 : null,
    pctPeriodico: janela.length
      ? (janela.filter((o) => o.issn).length / janela.length) * 100 : null,
    orientacoes: orient.length,
    patentes: tec.filter((t) => t.tipo === "patente").length,
    software: tec.filter((t) => t.tipo === "software").length,
    citacoes,
    semDoiSemPeriodico: janela.filter((o) => !o.doi && !o.issn).length,
    ambiguas: janela.filter((o) => o.ano_ambiguo).length,
    comEstrato: janela.filter((o) => o.estrato).length,
  };
}

const periodoOficial = () =>
  estado.dados && estado.inicio === estado.dados.periodo.inicio
  && estado.fim === estado.dados.periodo.fim;

/* -------------------------------------------------------------- lista lateral */
function pessoasVisiveis() {
  const termo = estado.busca.trim().toLowerCase();
  return estado.dados.pesquisadores.filter((p) => {
    if (estado.ppg && p.ppg !== estado.ppg) return false;
    if (!termo) return true;
    return [p.nome, p.nome_exibicao, p.lattes_id, p.orcid, ...(p.nomes_citacao || [])]
      .filter(Boolean).some((v) => String(v).toLowerCase().includes(termo));
  });
}

function desenharLista() {
  const alvo = $("#pessoas");
  alvo.replaceChildren();
  const pessoas = pessoasVisiveis();
  const maximo = Math.max(1, ...pessoas.map((p) => noPeriodo(p.obras).length));

  $("#contagem").textContent =
    `${pessoas.length} de ${estado.dados.pesquisadores.length} pesquisadores`;

  for (const pessoa of pessoas) {
    const obras = noPeriodo(pessoa.obras).length;
    const botao = el("button", {
      type: "button",
      className: `pessoa${estado.pessoa === pessoa.id ? " ativa" : ""}`,
    });
    botao.append(
      el("span", { className: "nome", textContent: pessoa.nome_exibicao || pessoa.nome }),
      el("span", { className: "obras", textContent: obras }),
      el("span", {
        className: "meta",
        textContent: [pessoa.ppg, pessoa.categoria].filter(Boolean).join(" · ")
          || (pessoa.lattes_id ? `lattes ${pessoa.lattes_id}` : "sem vínculo registrado"),
      }));
    const barra = el("span", { className: "barra" });
    barra.append(el("i", { style: `width:${(obras / maximo) * 100}%` }));
    botao.append(barra);
    botao.addEventListener("click", () => {
      estado.pessoa = pessoa.id;
      estado.visao = "pesquisador";
      sincronizarAbasTopo();
      desenhar();
      $("#palco").focus();
    });
    alvo.append(el("li", {}, botao));
  }
}

/* -------------------------------------------------------------------- ficha */
function cabecalho(pessoa) {
  const ids = el("p", { className: "ids" });
  const par = (rot, val, href) => {
    if (!val) return null;
    const valor = href
      ? el("a", { href, textContent: val, target: "_blank", rel: "noopener" })
      : document.createTextNode(val);
    return el("span", {}, [el("b", { textContent: `${rot} ` }), valor]);
  };
  ids.append(...[
    par("Lattes", pessoa.lattes_id,
        pessoa.lattes_id ? `http://lattes.cnpq.br/${pessoa.lattes_id}` : null),
    par("ORCID", pessoa.orcid,
        pessoa.orcid ? `https://orcid.org/${pessoa.orcid}` : null),
    par("BrCris", pessoa.brcris_id),
    par("currículo atualizado em", pessoa.curriculo_atualizado_em),
  ].filter(Boolean));

  const chips = el("div", { className: "chips" });
  if (pessoa.ppg) chips.append(el("span", { className: "chip forte", textContent: pessoa.ppg }));
  if (pessoa.categoria) chips.append(el("span", { className: "chip", textContent: pessoa.categoria }));
  if (!pessoa.ppg) {
    chips.append(el("span", {
      className: "chip", textContent: "vínculo não informado",
      dataset: { tip: "O vínculo docente↔PPG vem da secretaria ou dos dados abertos da CAPES — nunca do BrCris." },
    }));
  }

  const esquerda = el("div", {}, [
    el("h1", { textContent: pessoa.nome_exibicao || pessoa.nome }), ids, chips,
  ]);

  const assinaturas = (pessoa.nomes_citacao || []).length
    ? el("div", { className: "assinaturas" }, [
        el("b", { textContent: "Nomes de citação" }),
        document.createTextNode(pessoa.nomes_citacao.join(" · ")),
      ])
    : null;

  return el("header", { className: "ficha-topo" }, [esquerda, assinaturas]);
}

function kpis(ind) {
  const sufixo = periodoOficial() ? "exportado pelo motor" : "recalculado na tela";
  const tiles = [
    [num(ind.obras), "obras no período", `${estado.inicio}–${estado.fim} · ${sufixo}`],
    [num(ind.artigos), "artigos", "no período"],
    [pct(ind.pctDoi), "com DOI", `${pct(ind.pctPeriodico)} com periódico`],
    [num(ind.orientacoes), "orientações concluídas", "no período"],
    [num(ind.patentes + ind.software), "produção técnica",
      `${ind.patentes} patente(s) · ${ind.software} software`],
    [num(ind.citacoes), "citações", "OpenAlex ou Crossref"],
  ];
  return el("div", { className: "kpis" }, tiles.map(([v, k, s]) =>
    el("div", { className: "kpi" }, [
      el("p", { className: "v", textContent: v }),
      el("p", { className: "k", textContent: k }),
      el("p", { className: "s", textContent: s }),
    ])));
}

function grafico(pessoa) {
  const serie = (pessoa.producao_por_ano || [])
    .filter((p) => p.ano >= estado.inicio && p.ano <= estado.fim);
  const secao = el("section", { className: "secao" });
  secao.append(el("div", { className: "secao-topo" }, [
    el("h2", { textContent: "Produção por ano" }),
    el("p", { className: "nota", textContent: `${estado.inicio}–${estado.fim}` }),
  ]));

  if (!serie.length) {
    secao.append(el("p", { className: "nota",
      textContent: "Nenhuma obra datada nesta janela." }));
    return secao;
  }

  const maximo = Math.max(...serie.map((p) => p.total));
  const grafico = el("div", { className: "serie" });
  for (const ponto of serie) {
    const coluna = el("div", { className: "coluna" });
    coluna.append(el("p", { className: "total", textContent: ponto.total || "" }));
    const pilha = el("div", {
      className: "pilha",
      style: `height:${(ponto.total / maximo) * 118}px`,
    });
    for (const [tipo, rotulo] of TIPOS) {
      const n = ponto[tipo] || 0;
      if (!n) continue;
      pilha.append(el("div", {
        style: `flex:${n};background:${COR[tipo]}`,
        dataset: { tip: `<b>${n}</b> ${rotulo.toLowerCase()} em ${ponto.ano}` },
      }));
    }
    coluna.append(pilha, el("p", { className: "ano", textContent: ponto.ano }));
    grafico.append(coluna);
  }
  secao.append(grafico);

  const totais = {};
  for (const ponto of serie) {
    for (const [tipo] of TIPOS) totais[tipo] = (totais[tipo] || 0) + (ponto[tipo] || 0);
  }
  const legenda = el("div", { className: "legenda" });
  for (const [tipo, rotulo] of TIPOS) {
    if (!totais[tipo]) continue;
    legenda.append(el("span", {}, [
      el("i", { style: `background:${COR[tipo]}` }),
      document.createTextNode(rotulo),
      el("b", { textContent: totais[tipo] }),
    ]));
  }
  secao.append(legenda);
  return secao;
}

function tabela(colunas, linhas, vazio) {
  if (!linhas.length) return el("p", { className: "nota", textContent: vazio });
  const thead = el("thead", {}, el("tr", {}, colunas.map(
    (c) => el("th", { textContent: c.rot, className: c.num ? "num" : "" }))));
  const tbody = el("tbody", {}, linhas.map((linha) =>
    el("tr", {}, colunas.map((c) => {
      const td = el("td", { className: [c.num ? "num" : "", c.cls || ""].join(" ").trim() });
      const conteudo = c.render(linha);
      if (conteudo != null) td.append(conteudo);
      return td;
    }))));
  return el("div", { className: "tabelawrap" }, el("table", {}, [thead, tbody]));
}

function abaProducao(pessoa) {
  const obras = noPeriodo(pessoa.obras)
    .slice()
    .sort((a, b) => (b.ano || 0) - (a.ano || 0) || a.titulo.localeCompare(b.titulo, "pt"));
  return tabela([
    { rot: "Ano", num: true, render: (o) => {
        const span = el("span", { textContent: o.ano ?? "—" });
        if (!o.ano_ambiguo) return span;
        return el("span", {}, [span, el("span", {
          className: "alerta", textContent: " ⚠",
          dataset: { tip: `Mais de um ano em publicationDate: <b>${o.ano_ambiguo}</b>. Regra de desempate é decisão pendente — conferir no Lattes.` },
        })]);
      } },
    { rot: "Tipo", render: (o) => el("span", {
        className: "marca-tipo", textContent: ROTULO[o.tipo] || o.tipo || "—",
        style: `--cor:${COR[o.tipo] || "var(--neutro)"}`,
      }) },
    { rot: "Título", cls: "tit", render: (o) => o.titulo },
    { rot: "Periódico", render: (o) => o.periodico
        || el("span", { className: "falta", textContent: o.issn || "—" }) },
    { rot: "Qualis", render: (o) => o.estrato
        ? el("span", { className: "estrato", textContent: o.estrato })
        : el("span", { className: "falta", textContent: "—",
            dataset: { tip: "Sem estrato: falta a planilha Qualis do ciclo, ou o ISSN não casou." } }) },
    { rot: "DOI", render: (o) => o.doi
        ? el("a", { className: "doi", href: `https://doi.org/${o.doi}`,
                    textContent: o.doi, target: "_blank", rel: "noopener" })
        : el("span", { className: "falta", textContent: "sem DOI" }) },
    { rot: "Citações", num: true, render: (o) => o.citacoes == null
        ? el("span", { className: "falta", textContent: "—" }) : String(o.citacoes) },
  ], obras, "Nenhuma obra nesta janela. Rode a coleta para popular.");
}

function abaOrientacoes(pessoa) {
  const linhas = pessoa.orientacoes.slice()
    .sort((a, b) => (b.ano || 0) - (a.ano || 0));
  return tabela([
    { rot: "Ano", num: true, render: (o) => o.ano ?? "—" },
    { rot: "Nível", render: (o) => NIVEL[o.nivel] || o.nivel || "—" },
    { rot: "Papel", render: (o) => o.papel === "coorientacao" ? "Coorientação" : "Orientação" },
    { rot: "Orientando", render: (o) => o.orientando || "—" },
    { rot: "Situação", render: (o) => o.situacao || "—" },
    { rot: "Fonte", render: (o) => el("span", { className: "doi", textContent: o.fonte || "—" }) },
  ], linhas, "Nenhuma orientação registrada.");
}

function abaTecnica(pessoa) {
  return tabela([
    { rot: "Ano", num: true, render: (t) => t.ano ?? "—" },
    { rot: "Tipo", render: (t) => t.tipo || "—" },
    { rot: "Título", cls: "tit", render: (t) => t.titulo || "—" },
    { rot: "Situação", render: (t) => t.situacao || "—" },
    { rot: "Registro", render: (t) => el("span", { className: "doi", textContent: t.numero || "—" }) },
  ], pessoa.tecnica, "Nenhuma patente ou software registrado.");
}

function medidor(rotulo, valor, total, obs) {
  const p = total ? (valor / total) * 100 : 0;
  const m = el("div", { className: "medidor" });
  m.append(el("div", { className: "rot" }, [
    el("span", { textContent: rotulo }),
    el("b", { textContent: `${valor}/${total} · ${pct(p)}` }),
  ]));
  const tr = el("div", { className: "tr" });
  tr.append(el("i", { style: `width:${p}%` }));
  m.append(tr, el("p", { className: "obs", textContent: obs }));
  return m;
}

function abaCobertura(pessoa, ind) {
  const total = ind.obras;
  const janela = noPeriodo(pessoa.obras);
  const bloco = el("div", { className: "medidores" }, [
    medidor("Com DOI", janela.filter((o) => o.doi).length, total,
      "A chave do enriquecimento no OpenAlex e no Crossref."),
    medidor("Com periódico identificado", janela.filter((o) => o.issn).length, total,
      "Sem ISSN não há como buscar o estrato Qualis."),
    medidor("Com estrato Qualis", ind.comEstrato, total,
      "Depende da planilha do ciclo carregada por área."),
    medidor("Com data sem ambiguidade", total - ind.ambiguas, total,
      "Mais de um ano no mesmo campo exige regra de desempate."),
  ]);
  const nota = el("p", { className: "nota", style: "margin-top:18px" });
  nota.append(
    `${ind.semDoiSemPeriodico} obra(s) desta janela estão sem DOI e sem periódico — `,
    el("b", { textContent: "é o XML do Lattes do docente que tapa esse buraco" }),
    ". Nenhuma obra traz vínculo com o PPG nem identificador OpenAlex vindos do BrCris; "
    + "esses dois campos vêm sempre de outra fonte.");
  bloco.append();
  return el("div", {}, [bloco, nota]);
}

function ficha() {
  const pessoa = estado.dados.pesquisadores.find((p) => p.id === estado.pessoa);
  if (!pessoa) return vazio("Selecione um pesquisador na lista à esquerda.");
  const ind = indicadoresDaTela(pessoa);

  const abas = [
    ["producao", "Produção bibliográfica", noPeriodo(pessoa.obras).length],
    ["orientacoes", "Orientações", pessoa.orientacoes.length],
    ["tecnica", "Produção técnica", pessoa.tecnica.length],
    ["cobertura", "Cobertura e lacunas", null],
  ];
  const barra = el("div", { className: "abas", role: "tablist" });
  for (const [chave, rotulo, n] of abas) {
    const botao = el("button", {
      type: "button", role: "tab",
      className: `aba${estado.aba === chave ? " ativa" : ""}`,
      textContent: rotulo,
    });
    if (n != null) botao.append(el("span", { className: "n", textContent: n }));
    botao.addEventListener("click", () => { estado.aba = chave; desenhar(); });
    barra.append(botao);
  }

  const conteudo = { producao: abaProducao, orientacoes: abaOrientacoes,
                     tecnica: abaTecnica, cobertura: abaCobertura };
  const detalhe = el("section", { className: "secao" }, [
    barra, conteudo[estado.aba](pessoa, ind),
  ]);

  return el("div", {}, [cabecalho(pessoa), kpis(ind), grafico(pessoa), detalhe]);
}

/* ------------------------------------------------------------------ programa */
function programa() {
  const pessoas = pessoasVisiveis();
  if (!pessoas.length) return vazio("Nenhum pesquisador neste filtro.");

  const todas = pessoas.flatMap((p) => noPeriodo(p.obras));
  const unicas = new Map(todas.map((o) => [o.id, o]));
  const obras = [...unicas.values()];
  const porTipo = {};
  for (const obra of obras) porTipo[obra.tipo || "outro"] = (porTipo[obra.tipo || "outro"] || 0) + 1;

  const resumo = el("div", { className: "kpis" }, [
    [num(pessoas.length), "pesquisadores", "na lista filtrada"],
    [num(obras.length), "obras distintas",
      `${todas.length} autorias · ${todas.length - obras.length} em coautoria interna`],
    [pct(obras.length ? obras.filter((o) => o.doi).length / obras.length * 100 : 0),
      "com DOI", "chave do enriquecimento"],
    [num(pessoas.reduce((s, p) => s + p.orientacoes.length, 0)), "orientações", "no acervo"],
    [num(pessoas.reduce((s, p) => s + p.tecnica.length, 0)), "produção técnica",
      "patentes e software"],
  ].map(([v, k, s]) => el("div", { className: "kpi" }, [
    el("p", { className: "v", textContent: v }),
    el("p", { className: "k", textContent: k }),
    el("p", { className: "s", textContent: s }),
  ])));

  // ranking por obras no periodo
  const ordenadas = pessoas.slice().sort(
    (a, b) => noPeriodo(b.obras).length - noPeriodo(a.obras).length);
  const maximo = Math.max(1, ...ordenadas.map((p) => noPeriodo(p.obras).length));
  const rank = el("div", { className: "rank" });
  for (const pessoa of ordenadas) {
    const janela = noPeriodo(pessoa.obras);
    const artigos = janela.filter((o) => o.tipo === "artigo").length;
    const linha = el("button", { type: "button", className: "rrow" });
    linha.addEventListener("click", () => {
      estado.pessoa = pessoa.id; estado.visao = "pesquisador";
      sincronizarAbasTopo(); desenhar();
    });
    const track = el("div", { className: "rtrack",
      style: `width:${(janela.length / maximo) * 100}%` });
    if (artigos) {
      track.append(el("div", { style: `flex:${artigos};background:${COR.artigo}`,
        dataset: { tip: `<b>${artigos}</b> artigos` } }));
    }
    if (janela.length - artigos) {
      track.append(el("div", {
        style: `flex:${janela.length - artigos};background:${COR.evento};border-radius:0 3px 3px 0`,
        dataset: { tip: `<b>${janela.length - artigos}</b> demais tipos` } }));
    }
    linha.append(
      el("span", { className: "rnome", textContent: pessoa.nome_exibicao || pessoa.nome }),
      el("div", {}, track),
      el("span", { className: "rtot", textContent: janela.length }));
    rank.append(linha);
  }

  const composicao = el("div", { className: "legenda" });
  for (const [tipo, rotulo] of TIPOS) {
    if (!porTipo[tipo]) continue;
    composicao.append(el("span", {}, [
      el("i", { style: `background:${COR[tipo]}` }),
      document.createTextNode(rotulo),
      el("b", { textContent: porTipo[tipo] }),
    ]));
  }

  return el("div", {}, [
    el("header", { className: "ficha-topo" }, el("div", {}, [
      el("h1", { textContent: estado.ppg || "Todos os programas" }),
      el("p", { className: "ids" },
        el("span", { textContent: `${estado.inicio}–${estado.fim}` })),
    ])),
    resumo,
    el("section", { className: "secao" }, [
      el("div", { className: "secao-topo" }, [
        el("h2", { textContent: "Obras por pesquisador" }),
        el("p", { className: "nota",
          textContent: "Clique para abrir a ficha. Uma obra em coautoria interna conta para cada autor." }),
      ]),
      rank, composicao,
    ]),
  ]);
}

/* -------------------------------------------------------------------- coleta */
function coleta() {
  const coletas = estado.dados.coletas || [];
  const linhas = tabela([
    { rot: "Fonte", render: (c) => c.fonte },
    { rot: "Situação", render: (c) => el("span", {
        className: `status ${c.status === "ok" ? "ok" : c.status === "erro" ? "erro" : "running"}`,
        textContent: c.status }) },
    { rot: "Início", render: (c) => el("span", { className: "doi",
        textContent: c.inicio ? c.inicio.replace("T", " ").slice(0, 16) : "—" }) },
    { rot: "Documentos brutos", num: true, render: (c) => num(c.documentos) },
    { rot: "Erro", cls: "tit", render: (c) => c.erro || "—" },
  ], coletas, "Nenhuma coleta registrada ainda.");

  const q = estado.dados.qualis || {};
  return el("div", {}, [
    el("header", { className: "ficha-topo" }, el("div", {}, [
      el("h1", { textContent: "Procedência dos dados" }),
      el("p", { className: "ids" }, [
        el("span", {}, [el("b", { textContent: "exportado em " }),
          document.createTextNode((estado.dados.gerado_em || "").replace("T", " "))]),
        el("span", {}, [el("b", { textContent: "Qualis " }),
          document.createTextNode(q.ciclo
            ? `${q.ciclo} · ${q.area || "área não informada"} · ${num(q.periodicos_com_estrato)} periódicos`
            : "planilha não carregada")]),
      ]),
    ])),
    el("section", { className: "secao" }, [
      el("div", { className: "secao-topo" }, [
        el("h2", { textContent: "Execuções de coleta" }),
        el("p", { className: "nota",
          textContent: "Cada linha é um sync_run. Um conector que devolve vazio onde havia dados falha e não sobrescreve o núcleo." }),
      ]),
      linhas,
    ]),
    el("section", { className: "secao" }, [
      el("div", { className: "secao-topo" }, el("h2", { textContent: "Programas" })),
      tabela([
        { rot: "Sigla", render: (p) => p.sigla },
        { rot: "Nome", render: (p) => p.nome },
        { rot: "Código CAPES", render: (p) => el("span", { className: "doi",
            textContent: p.codigo_capes || "—" }) },
        { rot: "Área de avaliação", render: (p) => p.area_capes || "—" },
        { rot: "Docentes", num: true, render: (p) => num(p.n_docentes) },
      ], estado.dados.ppgs || [], "Nenhum programa cadastrado."),
    ]),
  ]);
}

/* ------------------------------------------------------------------ desenho */
function vazio(texto, comando) {
  const bloco = el("div", { className: "vazio" }, [
    el("h2", { textContent: "Nada para mostrar ainda" }),
    el("p", { textContent: texto }),
  ]);
  if (comando) bloco.append(el("p", {}, el("code", { textContent: comando })));
  return bloco;
}

function sincronizarAbasTopo() {
  for (const botao of document.querySelectorAll(".aba-topo")) {
    const ativa = botao.dataset.visao === estado.visao;
    botao.classList.toggle("ativa", ativa);
    botao.setAttribute("aria-selected", String(ativa));
  }
}

function desenhar() {
  desenharLista();
  const palco = $("#palco");
  const vista = { pesquisador: ficha, programa, coleta }[estado.visao];
  palco.replaceChildren(vista());
}

function ligarControles() {
  $("#busca").addEventListener("input", (e) => {
    estado.busca = e.target.value; desenharLista();
  });
  $("#filtro-ppg").addEventListener("change", (e) => {
    estado.ppg = e.target.value;
    const atual = estado.dados.pesquisadores.find((p) => p.id === estado.pessoa);
    if (atual && estado.ppg && atual.ppg !== estado.ppg) {
      estado.pessoa = pessoasVisiveis()[0]?.id ?? null;
    }
    desenhar();
  });
  for (const id of ["#periodo-inicio", "#periodo-fim"]) {
    $(id).addEventListener("change", () => {
      const i = parseInt($("#periodo-inicio").value, 10);
      const f = parseInt($("#periodo-fim").value, 10);
      if (Number.isFinite(i) && Number.isFinite(f) && i <= f) {
        estado.inicio = i; estado.fim = f; desenhar();
      } else {
        $("#periodo-inicio").value = estado.inicio;
        $("#periodo-fim").value = estado.fim;
      }
    });
  }
  for (const botao of document.querySelectorAll(".aba-topo")) {
    botao.addEventListener("click", () => {
      estado.visao = botao.dataset.visao; sincronizarAbasTopo(); desenhar();
    });
  }
}

async function iniciar() {
  const carregado = await carregar();
  if (!carregado) {
    $("#palco").replaceChildren(vazio(
      "Não encontrei app/data.json nem app/data.exemplo.json. Gere a exportação:",
      "python -m obsppg export"));
    return;
  }
  estado.dados = carregado.dados;
  estado.exemplo = carregado.exemplo;
  estado.inicio = carregado.dados.periodo?.inicio ?? 2021;
  estado.fim = carregado.dados.periodo?.fim ?? 2024;
  estado.pessoa = carregado.dados.pesquisadores[0]?.id ?? null;

  $("#periodo-inicio").value = estado.inicio;
  $("#periodo-fim").value = estado.fim;

  const seletor = $("#filtro-ppg");
  seletor.append(el("option", { value: "", textContent: "Todos" }));
  for (const ppg of carregado.dados.ppgs || []) {
    seletor.append(el("option", { value: ppg.sigla,
      textContent: `${ppg.sigla}${ppg.area_capes ? ` · ${ppg.area_capes}` : ""}` }));
  }

  $("#carimbo").textContent = [
    `exportado ${(carregado.dados.gerado_em || "").slice(0, 16).replace("T", " ")}`,
    `${carregado.dados.pesquisadores.length} pesquisadores`,
  ].join("\n");

  if (estado.exemplo) {
    const aviso = $("#aviso");
    aviso.hidden = false;
    aviso.innerHTML = "<b>Dados de demonstração.</b> Pessoas e obras fictícias, geradas "
      + "das fixtures de teste — nenhum registro de pesquisador real. Para ver o PPG: "
      + "<code>python -m obsppg ingest brcris --docentes docentes.txt</code> e depois "
      + "<code>python -m obsppg export</code>.";
  }

  ligarControles();
  desenhar();
}

iniciar();
