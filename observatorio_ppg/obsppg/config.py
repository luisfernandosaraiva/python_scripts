"""Configuracao por variavel de ambiente, com padroes de piloto."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACOTE = Path(__file__).resolve().parent
RAIZ = PACOTE.parent


def _caminho(var: str, padrao: Path) -> Path:
    valor = os.environ.get(var)
    return Path(valor).expanduser().resolve() if valor else padrao


@dataclass(frozen=True)
class Config:
    """Caminhos e parametros de rede do projeto."""

    banco: Path = _caminho("OBSPPG_DB", RAIZ / "data" / "observatorio_ppg.sqlite3")
    raw: Path = _caminho("OBSPPG_RAW", RAIZ / "data" / "raw")
    export: Path = _caminho("OBSPPG_EXPORT", RAIZ / "app" / "data.json")

    brcris_base: str = os.environ.get("OBSPPG_BRCRIS", "https://brcris.ibict.br")
    brcris_carga: str = os.environ.get("OBSPPG_BRCRIS_CARGA", "nov2025")
    openalex_base: str = "https://api.openalex.org"
    crossref_base: str = "https://api.crossref.org"
    orcid_base: str = "https://pub.orcid.org/v3.0"

    # OpenAlex e Crossref pedem identificacao no User-Agent (polite pool).
    contato: str = os.environ.get("OBSPPG_CONTATO", "")
    timeout: int = int(os.environ.get("OBSPPG_TIMEOUT", "60"))
    pausa: float = float(os.environ.get("OBSPPG_PAUSA", "0.34"))

    def preparar(self) -> None:
        self.banco.parent.mkdir(parents=True, exist_ok=True)
        self.raw.mkdir(parents=True, exist_ok=True)
        self.export.parent.mkdir(parents=True, exist_ok=True)

    @property
    def user_agent(self) -> str:
        base = f"obsppg/0.1 (Observatorio da Pos-Graduacao; +https://github.com/luisfernandosaraiva/python_scripts)"
        return f"{base} mailto:{self.contato}" if self.contato else base


CONFIG = Config()
