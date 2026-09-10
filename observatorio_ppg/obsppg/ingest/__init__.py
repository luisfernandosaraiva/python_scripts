"""Conectores de coleta.

Todo conector obedece ao mesmo contrato:

* abre um `SyncRun` e grava cada resposta em `raw_document` antes de interpretar;
* e idempotente — reexecutar nao duplica linha;
* **falha em vez de sobrescrever com lista vazia**: se a fonte devolver nada onde
  antes havia dados, o run termina com status `erro` e o nucleo fica intacto.
"""

from .base import ColetaVazia, Conector, ClienteHTTP  # noqa: F401
