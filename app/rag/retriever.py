import asyncio
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


async def search_docs(query: str, k: int = 5) -> list[ChunkResult]:
    """
    Embed query, query Chroma collection, return top-k results.
    Scores must be in [0, 1] (normalize cosine distance: score = 1 - distance).
    """
    if settings.GOOGLE_API_KEY:
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        response = genai.embed_content(
            model=settings.EMBED_MODEL,
            content=query,
            task_type="retrieval_query"
        )
        query_embedding = response['embedding']
    else:
        # Mock embedding for local testing if no API key
        query_embedding = [0.1] * 768

    chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
    try:
        collection = chroma_client.get_collection(name="helix_docs")
    except Exception:
        # If collection doesn't exist, return empty
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=k,
        include=["documents", "metadatas", "distances"]
    )

    chunk_results = []
    
    if results and results["ids"] and results["ids"][0]:
        ids = results["ids"][0]
        distances = results["distances"][0] if "distances" in results and results["distances"] else [0.0] * len(ids)
        documents = results["documents"][0] if "documents" in results and results["documents"] else [""] * len(ids)
        metadatas = results["metadatas"][0] if "metadatas" in results and results["metadatas"] else [{}] * len(ids)
        
        for i in range(len(ids)):
            # Normalize cosine distance: score = 1 - distance
            score = 1.0 - distances[i] if distances[i] <= 1.0 else 0.0
            score = max(0.0, min(1.0, score)) # Ensure it's in [0, 1]
            
            chunk_results.append(
                ChunkResult(
                    chunk_id=ids[i],
                    score=score,
                    text=documents[i],
                    metadata=metadatas[i] or {}
                )
            )
            
    return chunk_results
