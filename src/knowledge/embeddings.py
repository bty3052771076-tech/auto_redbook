from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable, Iterable
from uuid import uuid4

import numpy as np
from fastembed import TextEmbedding


MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_DIMENSIONS = 384
MODEL_REVISION = "qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"
CHUNK_VERSION = "char-token-320-overlap-48-v1"
_MODEL: TextEmbedding | None = None


def _workspace_model_dir() -> Path:
    path = Path(os.getenv("KNOWLEDGE_EMBEDDING_CACHE", "data/models/fastembed")).resolve()
    if path.drive.upper() != "E:":
        raise RuntimeError("EMBEDDING_CACHE_MUST_BE_ON_E: local model cache must remain on E:\\")
    path.mkdir(parents=True, exist_ok=True)
    hf_home = path.parent / "huggingface"
    hf_home.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(hf_home)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(hf_home / "hub")
    os.environ["HF_HUB_CACHE"] = str(hf_home / "hub")
    return path


def _asset_manifest(model_dir: Path) -> dict[str, str]:
    return {
        str(path.relative_to(model_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(model_dir.rglob("*"))
        if path.is_file() and path.name != "model-manifest.json"
    }


def get_embedding_model() -> "LocalEmbeddingModel":
    global _MODEL
    if _MODEL is None:
        model_dir = _workspace_model_dir()
        registered = {item["model"]: item for item in TextEmbedding.list_supported_models()}
        if MODEL_ID not in registered or int(registered[MODEL_ID].get("dim", 0)) != MODEL_DIMENSIONS:
            raise RuntimeError("EMBEDDING_MODEL_UNAVAILABLE: expected multilingual 384-d FastEmbed model is not registered")
        try:
            _MODEL = TextEmbedding(model_name=MODEL_ID, cache_dir=str(model_dir), threads=2, cuda=False)
        except Exception as exc:
            raise RuntimeError(f"EMBEDDING_MODEL_UNAVAILABLE: local model could not be loaded from E: ({type(exc).__name__})") from exc
        actual = _asset_manifest(model_dir)
        if not actual:
            _MODEL = None
            raise RuntimeError("EMBEDDING_MODEL_UNAVAILABLE: model loaded without verifiable local model files")
        manifest_path = model_dir / "model-manifest.json"
        if manifest_path.exists():
            expected = json.loads(manifest_path.read_text(encoding="utf-8"))
            if expected.get("model_id") != MODEL_ID or expected.get("model_revision") != MODEL_REVISION or expected.get("files") != actual:
                _MODEL = None
                raise RuntimeError("EMBEDDING_MODEL_CHECKSUM_MISMATCH: cached model files differ from the verified local manifest")
        else:
            manifest_path.write_text(json.dumps({"model_id": MODEL_ID, "model_revision": MODEL_REVISION, "dimensions": MODEL_DIMENSIONS, "files": actual}, ensure_ascii=False, indent=2), encoding="utf-8")
    return LocalEmbeddingModel(_MODEL)


class LocalEmbeddingModel:
    def __init__(self, model: TextEmbedding):
        self.model = model

    def embed_documents(self, texts: Iterable[str]) -> list[list[float]]:
        vectors = list(self.model.embed(list(texts), batch_size=64, parallel=1))
        result = [np.asarray(vector, dtype=np.float32).tolist() for vector in vectors]
        if any(len(vector) != MODEL_DIMENSIONS for vector in result):
            raise RuntimeError("EMBEDDING_DIMENSION_MISMATCH")
        return result

    def embed_query(self, text: str) -> list[float]:
        vectors = self.embed_documents([text])
        return vectors[0]


_TOKEN_RE = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:['’._-][A-Za-z0-9]+)*|[^\s]")


def chunk_document(title: str, body: str, *, max_tokens: int = 320, overlap: int = 48) -> list[dict[str, int | str]]:
    text = (str(title or "").strip() + "\n" + str(body or "").strip()).strip()
    tokens = list(_TOKEN_RE.finditer(text))
    if not tokens:
        return []
    chunks = []
    start_index = 0
    chunk_index = 0
    while start_index < len(tokens):
        end_index = min(len(tokens), start_index + max_tokens)
        start_char = tokens[start_index].start()
        end_char = tokens[end_index - 1].end()
        chunks.append({
            "chunk_index": chunk_index,
            "content": text[start_char:end_char],
            "char_start": start_char,
            "char_end": end_char,
            "token_count": end_index - start_index,
        })
        if end_index == len(tokens):
            break
        start_index = max(start_index + 1, end_index - overlap)
        chunk_index += 1
    return chunks


def prepare_chunks(documents: Iterable[dict], *, embedder=None) -> list[tuple[dict, list[dict]]]:
    source = list(documents)
    chunk_groups: list[tuple[dict, list[dict]]] = []
    flat: list[dict] = []
    for document in source:
        pieces = chunk_document(document.get("title", ""), document.get("body", ""))
        doc_chunks = []
        version = str(document["content_hash"])
        namespace = str(document.get("account_namespace") or "local")
        record_id = str(document["record_id"])
        for piece in pieces:
            chunk_id = hashlib.sha256(f"{namespace}\0{record_id}\0{version}\0{piece['chunk_index']}\0{CHUNK_VERSION}".encode()).hexdigest()
            chunk = {**piece, "chunk_id": chunk_id, "batch_id": uuid4().hex, "embedding": None}
            doc_chunks.append(chunk)
            flat.append(chunk)
        chunk_groups.append((document, doc_chunks))
    vectors = (embedder or get_embedding_model()).embed_documents(chunk["content"] for chunk in flat)
    if len(vectors) != len(flat):
        raise RuntimeError("EMBEDDING_BATCH_INCOMPLETE")
    for chunk, vector in zip(flat, vectors):
        chunk["embedding"] = vector
    return chunk_groups


def index_pending_documents(
    store,
    *,
    batch_size: int = 128,
    embedder=None,
    progress_callback: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, int]:
    indexed_documents = 0
    indexed_chunks = 0
    pending = store.pending_documents(limit=batch_size)
    if not pending:
        return {"indexed_documents": 0, "indexed_chunks": 0}
    worker = embedder or get_embedding_model()
    while pending:
        groups = prepare_chunks(pending, embedder=worker)
        for document, chunks in groups:
            if chunks:
                indexed_chunks += store.upsert_chunks(document["record_id"], chunks, account_namespace=document["account_namespace"])
            indexed_documents += 1
        if progress_callback:
            progress_callback({
                **store.index_progress(),
                "indexed_documents_this_run": indexed_documents,
                "indexed_chunks_this_run": indexed_chunks,
            })
        pending = store.pending_documents(limit=batch_size)
    return {"indexed_documents": indexed_documents, "indexed_chunks": indexed_chunks}
