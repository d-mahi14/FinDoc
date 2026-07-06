"""
ChromaDB vector store wrapper for indexing and querying document chunks.
Uses sentence-transformers for embeddings, PersistentClient for storage.
"""

import os
from typing import Any

# pyrefly: ignore [missing-import]
import chromadb
# pyrefly: ignore [import, missing-import]
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from app.models.schemas import Chunk, ChunkMetadata


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHROMA_PERSIST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "chroma_data"
)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
COLLECTION_NAME = "findocs_chunks"


# ---------------------------------------------------------------------------
# Singleton Setup
# ---------------------------------------------------------------------------

_chroma_client: chromadb.PersistentClient | None = None
_embedding_fn: SentenceTransformerEmbeddingFunction | None = None
_collection: chromadb.Collection | None = None


def _get_embedding_fn() -> SentenceTransformerEmbeddingFunction:
    """Get or create the sentence-transformers embedding function."""
    global _embedding_fn
    if _embedding_fn is None:
        print(f"[VectorStore] Loading embedding model: {EMBEDDING_MODEL}")
        _embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL,
            device="cpu"
        )
        print(f"[VectorStore] Embedding model loaded successfully")
    return _embedding_fn


def _get_collection() -> chromadb.Collection:
    """Get or create the ChromaDB collection."""
    global _chroma_client, _collection
    if _collection is None:
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        _collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=_get_embedding_fn(),
            metadata={"hnsw:space": "cosine"}
        )
        print(f"[VectorStore] ChromaDB collection '{COLLECTION_NAME}' ready "
              f"({_collection.count()} existing chunks)")
    return _collection


def init_vector_store():
    """Initialize the vector store eagerly (called at app startup)."""
    _get_collection()


# ---------------------------------------------------------------------------
# Text Chunking (Rule-Based, No LLM)
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    max_tokens: int = 500,
    overlap_tokens: int = 50,
    metadata: dict | None = None,
    company_symbol: str = "",
) -> list[Chunk]:
    """
    Split text into chunks of ~max_tokens (approximated as words * 1.3).
    Uses paragraph/sentence boundaries for clean splits.
    No LLM involved — purely rule-based.
    """
    if not text or not text.strip():
        return []

    meta = metadata or {}

    # Split into paragraphs first
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    chunks: list[Chunk] = []
    current_text = ""
    current_word_count = 0
    # Approximate: 1 token ≈ 0.75 words, so max_tokens ≈ max_tokens * 0.75 words
    max_words = int(max_tokens * 0.75)
    overlap_words = int(overlap_tokens * 0.75)

    for para in paragraphs:
        para_words = len(para.split())

        # If adding this paragraph exceeds the limit, flush current chunk
        if current_word_count + para_words > max_words and current_text:
            chunk_meta = ChunkMetadata(
                source_type=meta.get("source_type", ""),
                document_date=meta.get("document_date", ""),
                section=meta.get("section", ""),
                company_symbol=company_symbol,
                original_source=meta.get("original_source", ""),
            )
            chunks.append(Chunk(text=current_text.strip(), metadata=chunk_meta))

            # Keep overlap: last N words of current chunk
            words = current_text.split()
            if overlap_words > 0 and len(words) > overlap_words:
                current_text = " ".join(words[-overlap_words:]) + "\n\n" + para
                current_word_count = overlap_words + para_words
            else:
                current_text = para
                current_word_count = para_words
        else:
            current_text = (current_text + "\n\n" + para).strip() if current_text else para
            current_word_count += para_words

    # Flush remaining text
    if current_text.strip():
        chunk_meta = ChunkMetadata(
            source_type=meta.get("source_type", ""),
            document_date=meta.get("document_date", ""),
            section=meta.get("section", ""),
            company_symbol=company_symbol,
            original_source=meta.get("original_source", ""),
        )
        chunks.append(Chunk(text=current_text.strip(), metadata=chunk_meta))

    return chunks


# ---------------------------------------------------------------------------
# CRUD Operations
# ---------------------------------------------------------------------------

def add_chunks(company_symbol: str, chunks: list[Chunk]) -> int:
    """
    Add or upsert chunks into ChromaDB.
    Returns the number of chunks added.
    """
    if not chunks:
        return 0

    collection = _get_collection()

    ids = []
    documents = []
    metadatas = []

    for chunk in chunks:
        ids.append(chunk.chunk_id)
        documents.append(chunk.text)
        metadatas.append({
            "source_type": chunk.metadata.source_type,
            "document_date": chunk.metadata.document_date,
            "section": chunk.metadata.section,
            "company_symbol": company_symbol.upper(),
            "original_source": chunk.metadata.original_source,
            "chunk_id": chunk.chunk_id,
        })

    # Upsert in batches (ChromaDB recommends <5000 per call)
    batch_size = 500
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i:i + batch_size],
            documents=documents[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size],
        )

    print(f"[VectorStore] Added {len(chunks)} chunks for {company_symbol.upper()}")
    return len(chunks)


def query_chunks(
    company_symbol: str,
    query: str,
    n_results: int = 10,
    source_type: str = None,
    section: str = None,
) -> list[dict]:
    """
    Query ChromaDB for relevant chunks.
    Returns a list of dicts with {chunk_id, text, metadata, distance}.
    """
    collection = _get_collection()

    where_filter: dict[str, Any] = {"company_symbol": company_symbol.upper()}
    if source_type:
        where_filter["source_type"] = source_type
    if section:
        where_filter["section"] = section

    # Use $and if multiple filters
    if len(where_filter) > 1:
        where_clause = {"$and": [{k: v} for k, v in where_filter.items()]}
    else:
        where_clause = where_filter

    try:
        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count() or 1),
            where=where_clause if collection.count() > 0 else None,
        )
    except Exception as e:
        print(f"[VectorStore] Query error: {e}")
        # Retry without filters
        try:
            results = collection.query(
                query_texts=[query],
                n_results=min(n_results, max(collection.count(), 1)),
            )
        except Exception as e2:
            print(f"[VectorStore] Query retry also failed: {e2}")
            return []

    chunks = []
    if results and results["ids"] and results["ids"][0]:
        for i, chunk_id in enumerate(results["ids"][0]):
            chunks.append({
                "chunk_id": chunk_id,
                "text": results["documents"][0][i] if results["documents"] else "",
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0,
            })

    return chunks


def get_chunk_by_id(chunk_id: str) -> dict | None:
    """Retrieve a specific chunk by its ID."""
    collection = _get_collection()
    try:
        results = collection.get(ids=[chunk_id])
        if results and results["ids"]:
            return {
                "chunk_id": results["ids"][0],
                "text": results["documents"][0] if results["documents"] else "",
                "metadata": results["metadatas"][0] if results["metadatas"] else {},
            }
    except Exception as e:
        print(f"[VectorStore] Get chunk error: {e}")
    return None


def get_chunks_by_ids(chunk_ids: list[str]) -> list[dict]:
    """Retrieve multiple chunks by their IDs."""
    if not chunk_ids:
        return []

    collection = _get_collection()
    try:
        results = collection.get(ids=chunk_ids)
        chunks = []
        if results and results["ids"]:
            for i, cid in enumerate(results["ids"]):
                chunks.append({
                    "chunk_id": cid,
                    "text": results["documents"][i] if results["documents"] else "",
                    "metadata": results["metadatas"][i] if results["metadatas"] else {},
                })
        return chunks
    except Exception as e:
        print(f"[VectorStore] Get chunks error: {e}")
        return []


def delete_company_chunks(company_symbol: str) -> int:
    """Delete all chunks for a company (useful before re-indexing)."""
    collection = _get_collection()
    try:
        # Get all chunk IDs for this company
        results = collection.get(
            where={"company_symbol": company_symbol.upper()},
        )
        if results and results["ids"]:
            collection.delete(ids=results["ids"])
            print(f"[VectorStore] Deleted {len(results['ids'])} chunks for {company_symbol}")
            return len(results["ids"])
    except Exception as e:
        print(f"[VectorStore] Delete error: {e}")
    return 0


def get_company_chunk_count(company_symbol: str) -> int:
    """Get the number of indexed chunks for a company."""
    collection = _get_collection()
    try:
        results = collection.get(
            where={"company_symbol": company_symbol.upper()},
        )
        return len(results["ids"]) if results and results["ids"] else 0
    except Exception:
        return 0
