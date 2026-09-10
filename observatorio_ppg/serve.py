#!/usr/bin/env python3
"""Servidor local do Observatorio da Pos-Graduacao.

    python3 serve.py                 # http://localhost:8000
    python3 serve.py 8080            # outra porta
    python3 serve.py --no-browser

Duas telas:

* `/`             interface do observatorio — busca, ficha do pesquisador,
                  visao do programa e procedencia dos dados. Le `app/data.json`
                  (produzido por `python -m obsppg export`) e, na falta dele,
                  `app/data.exemplo.json`.
* `/diagnostico`  painel do documento de decisao, com as medicoes da sondagem.

Nao ha coleta aqui dentro: coleta e' CLI (`python -m obsppg ingest ...`), para
que rode agendada, com log e reexecucao idempotente.
"""

from __future__ import annotations

import http.server
import socketserver
import sys
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
APP = BASE / "app"
DIAGNOSTICO = BASE / "dashboard.html"

SKELETON = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Painel do piloto PPGBIOTEC</title>
<style>html{{color-scheme:light dark}}body{{margin:0}}img{{max-width:100%}}[hidden]{{display:none!important}}</style>
</head>
<body>
{body}
</body>
</html>
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serve `app/` como raiz e envolve o painel de diagnostico sob demanda."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP), **kwargs)

    def do_GET(self):  # noqa: N802 - assinatura da stdlib
        if self.path.split("?")[0].rstrip("/") in ("/diagnostico", "/dashboard"):
            return self._diagnostico()
        return super().do_GET()

    def _diagnostico(self):
        # dashboard.html guarda so o corpo da pagina, porque e a mesma fonte
        # publicada como artifact; o esqueleto entra aqui, em tempo de resposta.
        try:
            corpo = DIAGNOSTICO.read_text(encoding="utf-8")
        except OSError as err:
            self.send_error(500, "nao foi possivel ler dashboard.html", str(err))
            return
        self._enviar(SKELETON.format(body=corpo).encode("utf-8"))

    def _enviar(self, pagina: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(pagina)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(pagina)

    def end_headers(self):
        # o JSON de dados muda a cada export; cache do navegador so atrapalha
        if self.path.endswith(".json"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    porta = 8000
    for arg in sys.argv[1:]:
        if arg.isdigit():
            porta = int(arg)

    if not (APP / "index.html").exists():
        print(f"interface nao encontrada em {APP}", file=sys.stderr)
        return 1
    if not (APP / "data.json").exists() and not (APP / "data.exemplo.json").exists():
        print("aviso: nenhum data.json — rode `python -m obsppg export` "
              "ou `python3 tools/gerar_exemplo.py`", file=sys.stderr)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", porta), Handler) as httpd:
        url = f"http://localhost:{porta}"
        print(f"Observatorio da Pos-Graduacao em {url}")
        print(f"  interface .......... {url}/")
        print(f"  diagnostico ........ {url}/diagnostico")
        print("Ctrl+C para parar")
        if "--no-browser" not in sys.argv:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nservidor encerrado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
