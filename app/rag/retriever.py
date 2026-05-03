from dataclasses import dataclass
import re

import chromadb

from app.rag.embeddings import embed_text
from app.settings import settings


@dataclass
class ChunkResult:
    chunk_id: str
    score: float
    text: str
    metadata: dict


def _lexical_score(query: str, chunk: ChunkResult) -> int:
    query_terms = {term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2}
    text_terms = re.findall(r"[a-z0-9]+", chunk.text.lower())
    metadata_text = " ".join(str(value).lower() for value in chunk.metadata.values())
    score = 0

    for term in query_terms:
        stem = term[:-1] if term.endswith("e") else term
        if any(word.startswith(term) or word.startswith(stem) for word in text_terms):
            score += 2
        if term in metadata_text or stem in metadata_text:
            score += 1

    return score


# search the chroma collection and normalize distances to [0, 1]
async def search_docs(query: str, k: int = 5, rerank: bool = True) -> list[ChunkResult]:
    """Generates an embedding for a user query, searches ChromaDB, and optionally reranks matching chunks.
    
    Initial retrieval fetches k*2 (max 10) candidates, which are then reranked by the LLM 
    to find the top-k most relevant pieces of information.
    """
    initial_k = min(25, k * 5) if settings.USE_LOCAL_EMBEDDINGS else (min(10, k * 2) if rerank else k)
    
    query_embedding = embed_text(query, task_type="retrieval_query")

    chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
    try:
        # Access the pre-populated collection
        collection = chroma_client.get_collection(name="helix_docs")
    except Exception:
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=initial_k,
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

    if rerank and out:
        return out[:k]  # simple distance-based ranking (LLM reranker disabled to stay within free-tier RPM)

    return out


async def _rerank_chunks(query: str, chunks: list[ChunkResult], k: int) -> list[ChunkResult]:
    """Uses the LLM as a cross-encoder to select the top-k most relevant chunks from a candidate list."""
    if not settings.GOOGLE_API_KEY:
        return chunks[:k]

    model = genai.GenerativeModel("gemini-2.0-flash") # Use a fast model for reranking
    
    # Construct a prompt for reranking
    context = "\n\n".join([f"Chunk {i}:\n{c.text}" for i, c in enumerate(chunks)])
    prompt = f"""Given the user query: "{query}"
Rank the following document chunks by relevance. 
Return only a comma-separated list of the indices (e.g. 2, 0, 1) in order of most to least relevant.
Max {k} indices.

{context}"""

    try:
        resp = await asyncio.to_thread(model.generate_content, prompt)
        text = resp.text.strip()
        # Parse indices
        indices = [int(i.strip()) for i in text.split(",") if i.strip().isdigit()]
        
        reranked = []
        seen = set()
        for idx in indices:
            if 0 <= idx < len(chunks) and idx not in seen:
                reranked.append(chunks[idx])
                seen.add(idx)
        
        # Fallback if LLM failed to return valid indices
        if not reranked:
            return chunks[:k]
            
        return reranked[:k]
    except Exception:
        # Fallback to initial ordering on error
        return chunks[:k]

