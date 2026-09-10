"""Indicadores por pesquisador e por programa.

O que este modulo **nao** faz: calcular o IPD. A formula, os pesos e o tratamento
de autoria fracionada sao decisao pendente (§10 do documento de decisao) — sem
ela o motor pode ser construido, mas nenhum numero e publicavel. O que ele faz e
materializar os insumos que a interface mostra e que o motor consumira depois.
"""

from .indicadores import indicadores_do_pesquisador, producao_por_ano  # noqa: F401
