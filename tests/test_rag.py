from unittest.mock import patch

import chromadb
import pytest

from app.rag.retriever import search_docs

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_chroma():
    client = chromadb.Client()  # Ephemeral in-memory client
    collection = client.create_collection("helix_docs")

    collection.upsert(
        ids=["chunk_1", "chunk_2", "chunk_3"],
        embeddings=[[0.1] * 768, [0.2] * 768, [0.3] * 768],
        documents=["Deploy keys are...", "To rotate a deploy key...", "Billing page is..."],
        metadatas=[{"source": "keys.md"}, {"source": "keys.md"}, {"source": "billing.md"}]
    )

    with patch("chromadb.PersistentClient", return_value=client):
        yield client


@patch("google.generativeai.embed_content")
async def test_search_docs(mock_embed, mock_chroma):
    mock_embed.return_value = {"embedding": [0.1] * 768}

    # We must patch settings so the retrieval knows to use the mock key (or none)
    # The retriever doesn't care as long as it gets the collection.

    results = await search_docs("rotate deploy key", k=3)

    assert len(results) > 0
    assert all(isinstance(r.chunk_id, str) and r.chunk_id for r in results)
    assert all(0.0 <= r.score <= 1.0 for r in results)

    # The first result should be the one closest to [0.1] * 768, which is chunk_1
    assert results[0].chunk_id == "chunk_1"
