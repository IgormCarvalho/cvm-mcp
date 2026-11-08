"""Acesso HTTP à SEC com as três regras que mantêm o uso "seguro":

1. Identificação: todo request leva o User-Agent configurado pelo usuário.
2. Limite de taxa: no máximo MAX_REQUESTS_PER_SECOND requisições por
   segundo, controlado por um relógio compartilhado entre threads.
3. Cache local: arquivos ficam em `cache_dir()/sec`; dentro de `max_age`
   nem se consulta a SEC, e depois disso a revalidação é condicional
   (ETag/Last-Modified), então só se baixa de novo o que mudou.

Erros 429/5xx são repetidos com espera crescente; se a SEC estiver fora do
ar e houver cópia em cache, a cópia é usada (com aviso via `stale=True`).
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..config import cache_dir
from .config import (
    HTTP_MAX_RETRIES,
    HTTP_TIMEOUT_SECONDS,
    MAX_REQUESTS_PER_SECOND,
    user_agent,
)

_lock = threading.Lock()
_ultimo_request = 0.0


class SecHttpError(RuntimeError):
    pass


class SecNotFoundError(SecHttpError):
    pass


@dataclass
class Resposta:
    dados: dict | list
    stale: bool = False


def _sec_dir() -> Path:
    path = cache_dir() / "sec"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _throttle() -> None:
    global _ultimo_request
    intervalo = 1.0 / MAX_REQUESTS_PER_SECOND
    with _lock:
        agora = time.monotonic()
        espera = _ultimo_request + intervalo - agora
        if espera > 0:
            time.sleep(espera)
        _ultimo_request = time.monotonic()


def _meta_path(dest: Path) -> Path:
    return dest.with_suffix(dest.suffix + ".meta.json")


def _read_meta(dest: Path) -> dict:
    try:
        return json.loads(_meta_path(dest).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_meta(dest: Path, meta: dict) -> None:
    _meta_path(dest).write_text(json.dumps(meta), encoding="utf-8")


def _ler_json(dest: Path) -> dict | list:
    return json.loads(dest.read_text(encoding="utf-8"))


def _get(client: httpx.Client, url: str, headers: dict) -> httpx.Response:
    ultimo_erro: Exception | None = None
    for tentativa in range(HTTP_MAX_RETRIES + 1):
        _throttle()
        try:
            resposta = client.get(url, headers=headers)
        except httpx.TransportError as exc:
            ultimo_erro = exc
        else:
            if resposta.status_code not in (429, 500, 502, 503, 504):
                return resposta
            ultimo_erro = SecHttpError(f"SEC respondeu {resposta.status_code} para {url}")
        if tentativa < HTTP_MAX_RETRIES:
            time.sleep(min(2 ** tentativa, 8))
    raise SecHttpError(str(ultimo_erro))


def fetch_json(url: str, filename: str, max_age_seconds: float) -> Resposta:
    """Baixa (ou reaproveita do cache) um JSON da SEC."""
    dest = _sec_dir() / filename
    meta = _read_meta(dest)

    if dest.exists() and time.time() - meta.get("baixado_em", 0) < max_age_seconds:
        return Resposta(_ler_json(dest))

    headers = {"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}
    if dest.exists():
        if etag := meta.get("etag"):
            headers["If-None-Match"] = etag
        if last_modified := meta.get("last_modified"):
            headers["If-Modified-Since"] = last_modified

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
            resposta = _get(client, url, headers)
    except SecHttpError:
        if dest.exists():
            return Resposta(_ler_json(dest), stale=True)
        raise

    if resposta.status_code == 304 and dest.exists():
        meta["baixado_em"] = time.time()
        _write_meta(dest, meta)
        return Resposta(_ler_json(dest))
    if resposta.status_code == 404:
        raise SecNotFoundError(f"Não encontrado na SEC: {url}")
    if resposta.status_code == 403:
        raise SecHttpError(
            "A SEC recusou o acesso (403). Confira se SEC_MCP_USER_AGENT tem nome e e-mail válidos."
        )
    resposta.raise_for_status()

    dados = resposta.json()
    dest.write_text(json.dumps(dados), encoding="utf-8")
    _write_meta(
        dest,
        {
            "etag": resposta.headers.get("ETag"),
            "last_modified": resposta.headers.get("Last-Modified"),
            "source_url": url,
            "baixado_em": time.time(),
        },
    )
    return Resposta(dados)
