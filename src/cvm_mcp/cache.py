"""Download e cache local dos arquivos publicados pela CVM.

Usa requisições condicionais (ETag / Last-Modified) para evitar baixar de
novo um arquivo que não mudou no portal, e grava tudo dentro do cache_dir()
resolvido em config.py (portátil entre sistemas operacionais).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import httpx

from .config import HTTP_TIMEOUT_SECONDS, HTTP_USER_AGENT, cache_dir


def _meta_path(dest: Path) -> Path:
    return dest.with_suffix(dest.suffix + ".meta.json")


def _read_meta(dest: Path) -> dict:
    meta_path = _meta_path(dest)
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_meta(dest: Path, meta: dict) -> None:
    _meta_path(dest).write_text(json.dumps(meta), encoding="utf-8")


def download_file(url: str, filename: str | None = None) -> Path:
    """Baixa `url` para o cache local, reaproveitando o arquivo existente
    quando o servidor confirma (304) que não houve mudança. Retorna o
    caminho do arquivo em disco."""
    dest = cache_dir() / (filename or url.rsplit("/", 1)[-1])
    headers = {"User-Agent": HTTP_USER_AGENT}

    meta = _read_meta(dest)
    if dest.exists():
        if etag := meta.get("etag"):
            headers["If-None-Match"] = etag
        if last_modified := meta.get("last_modified"):
            headers["If-Modified-Since"] = last_modified

    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = client.get(url, headers=headers)

        if response.status_code == 304 and dest.exists():
            return dest

        response.raise_for_status()
        dest.write_bytes(response.content)
        _write_meta(
            dest,
            {
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "source_url": url,
            },
        )
        return dest


def ensure_extracted(zip_path: Path) -> Path:
    """Extrai um ZIP baixado da CVM para uma subpasta com o mesmo nome
    (sem extensão), pulando a extração se já tiver sido feita antes."""
    extract_dir = zip_path.with_suffix("")
    marker = extract_dir / ".extracted"
    if marker.exists():
        return extract_dir

    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    marker.write_text("ok", encoding="utf-8")
    return extract_dir
