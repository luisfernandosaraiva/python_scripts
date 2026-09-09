# Painel do piloto PPGBIOTEC

Dashboard estático (HTML único, sem build) que consolida a arquitetura recomendada e as
medições do documento `arquitetura_observatorio_ppg.md` — Observatório da Pós-Graduação
da Univates.

## O que o painel mostra

| Bloco | Origem no documento |
|---|---|
| Veredito e contraste 305 × 33 obras | §11.2, §12.1 |
| Produção por docente no quadriênio 2021–2024 | §12.3 |
| Composição das 305 obras e cobertura de campos por recorte | §12.4 |
| Lacunas e origem de cada dado que falta | §12.4 |
| Fontes de dados, papel e situação de acesso | §3 |
| Pipeline (raw imutável → cálculo → apresentação) | §2 |
| Pesos ilustrativos do IPD e requisitos de aceitação política | §6 |
| Receita do piloto, ponta a ponta | §12.5 |
| Plano de 4 sprints com critérios de aceite | §9 |
| Decisões pendentes antes de codificar | §10 |
| Ressalva de LGPD e de não-equivalência com a nota CAPES | §7 |

Todos os números são os medidos em 09/09/2026 contra o índice `brc-nov2025` do BrCris.
Nenhum valor foi estimado ou arredondado além do que consta no documento.

## Como abrir

```bash
python3 observatorio_ppg/serve.py          # http://localhost:8000, abre o navegador
python3 observatorio_ppg/serve.py 8080     # outra porta
python3 observatorio_ppg/serve.py --no-browser
```

Só a biblioteca padrão do Python — nada a instalar. `Ctrl+C` encerra.

`dashboard.html` guarda o corpo da página (sem `<html>`/`<head>`/`<body>`), porque é a
mesma fonte publicada como artifact; `serve.py` envolve esse corpo no esqueleto mínimo do
documento em tempo de resposta, para que exista uma única fonte de verdade. Por isso,
abrir `dashboard.html` direto pelo `file://` funciona na maioria dos navegadores, mas o
caminho previsto é o servidor.

A única dependência externa é a família IBM Plex, servida pelo Google Fonts, com fallback
para a pilha do sistema quando não houver rede. Tema claro e escuro seguem a preferência
do sistema.

## Notas de implementação

- Paleta categórica validada para daltonismo (ΔE CVD ≥ 8 em pares adjacentes) nas duas
  superfícies; rótulos diretos e tabela completa como canal secundário de identidade.
- Cada gráfico tem tooltip por marca; toda série colorida também aparece em tabela.
- Sem regra de negócio na tela: os dados vivem em arrays no topo do `<script>`, prontos
  para serem trocados pela saída de `obsppg/` quando o motor existir.
