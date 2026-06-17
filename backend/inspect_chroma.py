"""
Throwaway inspection script — peek at what an external ChromaDB actually contains.

Run against any Chroma instance to see, per collection:
  - how many chunks it holds
  - a sample of chunk IDs (these often encode a doc id, e.g. "doc123_0")
  - what metadata fields exist (and which look usable as doc_id / title)
  - a snippet of the chunk text
  - the embedding dimension (must match what DokOps is configured to use)

Usage:
    python inspect_chroma.py
    python inspect_chroma.py --host 10.0.0.5 --port 8001
    CHROMA_HOST=10.0.0.5 CHROMA_PORT=8001 python inspect_chroma.py

Nothing is written or modified — read-only.
"""
import argparse
import os
from collections import Counter


def _connect(host: str, port: int):
    import chromadb
    print(f"-> connecting to Chroma at {host}:{port} ...")
    try:
        client = chromadb.HttpClient(host=host, port=port)
        client.heartbeat()  # raises if unreachable
    except Exception as exc:
        raise SystemExit(
            f"[error] could not reach Chroma at {host}:{port}\n"
            f"        {type(exc).__name__}: {exc}\n"
            f"        Is a Chroma server running there? Point at the right host/port with "
            f"--host/--port (or CHROMA_HOST/CHROMA_PORT)."
        )
    print("[ok] connected\n")
    return client


def _infer_doc_id_from_chunk_id(chunk_id: str) -> str:
    """DokOps-style IDs look like '<doc_id>_<n>'. Strip a trailing _<int> if present."""
    if "_" in chunk_id:
        head, _, tail = chunk_id.rpartition("_")
        if tail.isdigit() and head:
            return head
    return chunk_id


def inspect_collection(col, sample_size: int = 5) -> None:
    name = col.name
    try:
        count = col.count()
    except Exception as exc:
        print(f"  ! could not count: {exc}")
        count = None

    print(f"== collection: {name!r}  (chunks: {count}) ==")
    if not count:
        print("  (empty)\n")
        return

    sample = col.get(limit=sample_size, include=["metadatas", "documents", "embeddings"])
    ids = sample.get("ids") or []
    metas = sample.get("metadatas") or []
    docs = sample.get("documents") or []
    embs = sample.get("embeddings") or []

    # Embedding dimension — the make-or-break for plug-and-play retrieval.
    dim = len(embs[0]) if embs and embs[0] is not None else "unknown"
    print(f"  embedding dimension: {dim}   "
          f"(384=all-MiniLM-L6-v2, 1536=text-embedding-3-small/ada-002)")

    # Which metadata keys exist across the sample?
    key_counter: Counter = Counter()
    for m in metas:
        key_counter.update((m or {}).keys())
    if key_counter:
        print(f"  metadata keys seen: {dict(key_counter)}")
    else:
        print("  metadata keys seen: NONE (chunks carry no metadata)")

    # Can we group chunks into documents?
    has_doc_id = "doc_id" in key_counter
    sample_inferred = {_infer_doc_id_from_chunk_id(i) for i in ids}
    id_encodes_doc = any(_infer_doc_id_from_chunk_id(i) != i for i in ids)
    print(f"  doc grouping:  metadata['doc_id']={has_doc_id}   "
          f"id-encodes-doc={id_encodes_doc}  (e.g. {sorted(sample_inferred)[:3]})")
    print(f"  title source:  metadata has "
          f"{[k for k in ('title','source_ref','source','filename') if k in key_counter] or 'NONE — would fall back to text snippet'}")

    print("  --- sample records ---")
    for i in range(min(sample_size, len(ids))):
        meta = metas[i] if i < len(metas) else {}
        text = (docs[i] if i < len(docs) else "") or ""
        snippet = text[:120].replace("\n", " ")
        print(f"   [{i}] id={ids[i]!r}")
        print(f"        meta={meta}")
        print(f"        text={snippet!r}{'…' if len(text) > 120 else ''}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a ChromaDB instance (read-only).")
    parser.add_argument("--host", default=os.getenv("CHROMA_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CHROMA_PORT", "8001")))
    parser.add_argument("--sample", type=int, default=5, help="records to sample per collection")
    args = parser.parse_args()

    client = _connect(args.host, args.port)

    collections = client.list_collections()
    if not collections:
        print("No collections found on this instance.")
        return

    names = [c.name for c in collections]
    print(f"Found {len(names)} collection(s): {names}")
    dokops_expected = {"knowledge_base", "incidents"}
    missing = dokops_expected - set(names)
    if missing:
        print(f"[warn] DokOps queries {sorted(dokops_expected)}; this instance is missing: {sorted(missing)}")
        print("  (chunks in differently-named collections won't be retrieved unless renamed/copied)\n")
    else:
        print()

    for c in collections:
        inspect_collection(client.get_collection(c.name), sample_size=args.sample)


if __name__ == "__main__":
    main()
