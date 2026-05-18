import glob
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

_encoder: SentenceTransformer | None = None
_index: faiss.IndexFlatL2 | None = None
_chunks: list[str] = []


def _get_encoder() -> SentenceTransformer:
    global _encoder
    if _encoder is None:
        _encoder = SentenceTransformer("all-MiniLM-L6-v2")
    return _encoder


def _chunk_markdown(text: str) -> list[str]:
    lines = text.split("\n")
    chunks = []
    current = []

    for line in lines:
        if line.startswith("## ") and current:
            chunks.append("\n".join(current).strip())
            current = []
        current.append(line)
    if current:
        chunks.append("\n".join(current).strip())

    return [c for c in chunks if c]


def load_knowledge_base(kb_dir: str | None = None) -> None:
    global _index, _chunks

    from app.debug_log import debug_log
    from app.config import settings as _settings
    from pathlib import Path as _Path

    if kb_dir is None:
        kb_dir = str(_Path(__file__).resolve().parents[2] / "knowledge_base")

    md_files = glob.glob(str(Path(kb_dir) / "*.md"))
    all_chunks = []
    for filepath in md_files:
        with open(filepath) as f:
            content = f.read()
        all_chunks.extend(_chunk_markdown(content))

    bad_timing = [
        c[:120]
        for c in all_chunks
        if "10 second" in c.lower() or "wait silently" in c.lower()
    ]

    if not all_chunks:
        _chunks = []
        _index = None
        # region agent log
        debug_log(
            hypothesis_id="H1",
            location="retrieval.py:load_knowledge_base",
            message="KB empty after load",
            data={"kb_dir": kb_dir, "md_files": md_files},
        )
        # endregion
        return

    encoder = _get_encoder()
    embeddings = encoder.encode(all_chunks, normalize_embeddings=True)
    dim = embeddings.shape[1]

    _index = faiss.IndexFlatL2(dim)
    _index.add(np.array(embeddings).astype("float32"))
    _chunks = all_chunks
    # region agent log
    debug_log(
        hypothesis_id="H1-H2",
        location="retrieval.py:load_knowledge_base",
        message="KB loaded",
        data={
            "kb_dir": kb_dir,
            "md_files": [Path(p).name for p in md_files],
            "chunk_count": len(all_chunks),
            "bad_timing_chunks": len(bad_timing),
            "sample_chunk": all_chunks[0][:100] if all_chunks else "",
        },
    )
    # endregion


def _search_sync(query: str, top_k: int) -> str:
    if _index is None or not _chunks:
        return ""

    encoder = _get_encoder()
    query_vec = encoder.encode([query], normalize_embeddings=True)
    distances, indices = _index.search(
        np.array(query_vec).astype("float32"), min(top_k, len(_chunks))
    )

    results = []
    for i in indices[0]:
        results.append(_chunks[i])
    return "\n\n".join(results)


def get_step_content_sync(step: int) -> str:
    """Direct chunk lookup by step number — more reliable than semantic search for numbered steps."""
    prefix = f"## Step {step} -"
    for chunk in _chunks:
        if chunk.startswith(prefix):
            return chunk
    return ""


def extract_step_responses(step_chunk: str) -> list[str]:
    """Extract assistant response sentences from a KB step chunk."""
    lines = step_chunk.split("\n")
    responses = []
    capture = False
    for line in lines:
        s = line.strip()
        if s == "### Assistant Response":
            capture = True
            continue
        if capture:
            if s.startswith("## ") or s == "---":
                break
            if not s:
                continue
            if s.startswith('"') and s.endswith('"'):
                s = s[1:-1]
            if s:
                responses.append(s)
    return responses


async def get_step_content(step: int) -> str:
    import asyncio

    return await asyncio.to_thread(get_step_content_sync, step)


async def search(query: str, top_k: int = 3) -> str:
    import asyncio

    return await asyncio.to_thread(_search_sync, query, top_k)
