from dataclasses import dataclass

import chromadb
import google.generativeai as genai

from app.settings import settings


@dataclass
class ChunkResult:
    chunk_id: str
    score: float
    text: str
    metadata: dict


# search the chroma collection and normalize distances to [0, 1]
async def search_docs(query: str, k: int = 5) -> list[ChunkResult]:
    """Generates an embedding for a user query, searches ChromaDB, and returns top-k matching document chunks.

    Args:
        query: The user's search string.
        k: The maximum number of document chunks to return. Defaults to 5.

    Returns:
        A list of ChunkResult objects containing the chunk text, metadata, and normalized similarity score.
    """
    if settings.GOOGLE_API_KEY:
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        resp = genai.embed_content(
            model=settings.EMBED_MODEL,
            content=query,
            task_type="retrieval_query",
        )
        query_embedding = resp["embedding"]
    else:
        # no key → dummy vector
        query_embedding = [0.1] * 768

    chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
    try:
        # Access the pre-populated collection
        collection = chroma_client.get_collection(name="helix_docs")
    except Exception:
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )

    out = []
    if results and results["ids"] and results["ids"][0]:
        ids = results["ids"][0]
        distances = results["distances"][0] if results.get("distances") else [0.0] * len(ids)
        documents = results["documents"][0] if results.get("documents") else [""] * len(ids)
        metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(ids)

        for i, chunk_id in enumerate(ids):
            # lower distance = more similar; cap to [0, 1]
            score = max(0.0, min(1.0, 1.0 - distances[i]))
            out.append(ChunkResult(
                chunk_id=chunk_id,
                score=score,
                text=documents[i],
                metadata=metadatas[i] or {},
            ))

    return out
