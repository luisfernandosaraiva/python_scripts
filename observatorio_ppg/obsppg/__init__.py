"""Observatorio da Pos-Graduacao — motor de coleta, resolucao e indicadores.

O pacote e puro Python: nenhuma regra de negocio vive na interface. A ordem das
camadas e sempre a mesma — coleta grava em `raw_document` imutavel, normalizacao
escreve no nucleo, calculo le do nucleo e grava evidencia por componente.
"""

__version__ = "0.1.0"
