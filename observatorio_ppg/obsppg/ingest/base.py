"""Infraestrutura comum aos conectores: HTTP educado, raw imutavel, sync_run."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import CONFIG
from ..models import RawDocument, SyncRun


class ColetaVazia(RuntimeError):
    """A fonte devolveu vazio onde havia dados. Falhar e' o comportamento correto."""


class ErroDeFonte(RuntimeError):
    """A fonte respondeu, mas fora do contrato esperado."""


class ClienteHTTP:
    """Sessao HTTP com User-Agent identificado, pausa entre chamadas e retentativa.

    A pausa existe porque OpenAlex, Crossref e ORCID pedem uso educado; o BrCris
    nao publica limite, entao aplicamos a mesma regra por precaucao.
    """

    def __init__(self, base: str = "", *, timeout: int | None = None,
                 pausa: float | None = None, headers: dict[str, str] | None = None):
        self.base = base.rstrip("/")
        self.timeout = timeout or CONFIG.timeout
        self.pausa = CONFIG.pausa if pausa is None else pausa
        self.sessao = requests.Session()
        self.sessao.headers.update({
            "User-Agent": CONFIG.user_agent,
            "Accept": "application/json",
        })
        if headers:
            self.sessao.headers.update(headers)
        self._ultima = 0.0

    def _esperar(self) -> None:
        if self.pausa <= 0:
            return
        delta = time.monotonic() - self._ultima
        if delta < self.pausa:
            time.sleep(self.pausa - delta)
        self._ultima = time.monotonic()

    def pedir(self, metodo: str, caminho: str, *, tentativas: int = 4,
              **kwargs: Any) -> requests.Response:
        url = caminho if caminho.startswith("http") else f"{self.base}/{caminho.lstrip('/')}"
        ultimo: Exception | None = None
        for tentativa in range(tentativas):
            self._esperar()
            try:
                resp = self.sessao.request(metodo, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as err:  # rede instavel
                ultimo = err
            else:
                if resp.status_code < 400:
                    return resp
                if resp.status_code in (429, 500, 502, 503, 504):
                    ultimo = ErroDeFonte(f"{resp.status_code} em {url}")
                else:
                    raise ErroDeFonte(
                        f"{resp.status_code} em {url}: {resp.text[:300]}")
            time.sleep(2 ** tentativa)
        raise ErroDeFonte(f"falha apos {tentativas} tentativas em {url}: {ultimo}")

    def get(self, caminho: str, **kwargs: Any) -> Any:
        return self.pedir("GET", caminho, **kwargs).json()

    def post(self, caminho: str, **kwargs: Any) -> Any:
        return self.pedir("POST", caminho, **kwargs).json()


class Conector:
    """Base dos conectores. Abre o `SyncRun`, grava raw, fecha com status."""

    nome: str = "generico"

    def __init__(self, s: Session, *, raw_dir: Path | None = None):
        self.s = s
        self.raw_dir = (raw_dir or CONFIG.raw) / self.nome
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.run: SyncRun | None = None

    # ---------------- sync_run ---------------- #
    def abrir(self, **params: Any) -> SyncRun:
        self.run = SyncRun(source=self.nome, params=json.dumps(params, ensure_ascii=False,
                                                              default=str))
        self.s.add(self.run)
        self.s.flush()
        return self.run

    def fechar(self, status: str = "ok", erro: str | None = None) -> None:
        if self.run is None:
            return
        self.run.finished_at = datetime.now(timezone.utc)
        self.run.status = status
        self.run.error = erro
        self.s.flush()

    # ---------------- raw imutavel ---------------- #
    def gravar_raw(self, conteudo: bytes | str | dict | list, *, ref: str,
                   media_type: str = "application/json") -> RawDocument:
        """Grava o conteudo como veio e devolve a linha de `raw_document`.

        Idempotente pelo par (source, source_ref, content_hash): recoletar o mesmo
        conteudo nao cria linha nova, o que mantem o recalculo estavel.
        """
        if isinstance(conteudo, (dict, list)):
            dados = json.dumps(conteudo, ensure_ascii=False, sort_keys=True,
                               indent=1).encode("utf-8")
        elif isinstance(conteudo, str):
            dados = conteudo.encode("utf-8")
        else:
            dados = conteudo

        digest = hashlib.sha256(dados).hexdigest()
        existente = self.s.scalar(
            select(RawDocument).where(
                RawDocument.source == self.nome,
                RawDocument.source_ref == ref,
                RawDocument.content_hash == digest,
            )
        )
        if existente is not None:
            return existente

        sufixo = {"application/json": "json", "application/xml": "xml",
                  "text/csv": "csv"}.get(media_type, "bin")
        destino = self.raw_dir / f"{digest[:16]}.{sufixo}"
        if not destino.exists():
            destino.write_bytes(dados)

        assert self.run is not None, "abrir() antes de gravar_raw()"
        doc = RawDocument(
            source=self.nome, source_ref=ref[:300], sync_run_id=self.run.id,
            content_hash=digest, media_type=media_type, path=str(destino),
        )
        self.s.add(doc)
        self.s.flush()
        self.run.n_documents = (self.run.n_documents or 0) + 1
        return doc

    # ---------------- guarda contra lista vazia ---------------- #
    def exigir_nao_vazio(self, itens: Any, o_que: str, anterior: int = 0) -> None:
        if not itens and anterior > 0:
            raise ColetaVazia(
                f"{self.nome}: {o_que} voltou vazio, mas havia {anterior} registro(s). "
                "Nada foi sobrescrito.")
