#!/usr/bin/env python3
"""Servidor local do painel do piloto PPGBIOTEC.

    python3 observatorio_ppg/serve.py            # http://localhost:8000
    python3 observatorio_ppg/serve.py 8080       # outra porta

dashboard.html e o corpo da pagina (sem <html>/<head>/<body>), porque e a mesma
fonte publicada como artifact. Este servidor envolve esse corpo no esqueleto
minimo do documento em tempo de resposta, para que o arquivo continue com uma
unica fonte de verdade.
"""

from __future__ import annotations

import http.server
import socketserver
import sys
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
BODY = BASE / "dashboard.html"

SKELETON = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>html{{color-scheme:light dark}}body{{margin:0}}img{{max-width:100%}}[hidden]{{display:none!important}}</style>
</head>
<body>
{body}
</body>
</html>
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE), **kwargs)

    def do_GET(self):  # noqa: N802 - assinatura da stdlib
        if self.path in ("/", "/index.html", "/dashboard.html"):
            return self.send_page()
        return super().do_GET()

    def send_page(self):
        try:
            body = BODY.read_text(encoding="utf-8")
        except OSError as err:
            self.send_error(500, "nao foi possivel ler dashboard.html", str(err))
            return
        page = SKELETON.format(body=body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    if not BODY.exists():
        print(f"dashboard.html nao encontrado em {BASE}", file=sys.stderr)
        return 1
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        url = f"http://localhost:{port}"
        print(f"Painel do piloto PPGBIOTEC em {url}  (Ctrl+C para parar)")
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
