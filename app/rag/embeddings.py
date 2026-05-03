import hashlib
import math
import re

from app.settings import settings


EMBEDDING_DIMENSION = 768


def deterministic_embedding(text: str, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    """Create a stable lexical embedding for offline/demo-safe retrieval."""
    vector = [0.0] * dimension
    tokens = re.findall(r"[a-z0-9]+", text.lower())

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return [0.0] * dimension

    return [value / norm for value in vector]


def embed_text(text: str, task_type: str) -> list[float]:
    """Embed text, preferring the demo-safe local embedding unless explicitly disabled."""
    if settings.USE_LOCAL_EMBEDDINGS or not settings.GOOGLE_API_KEY:
        return deterministic_embedding(text)

    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.GOOGLE_API_KEY)
        resp = genai.embed_content(
            model=settings.EMBED_MODEL,
            content=text,
            task_type=task_type,
        )
        return resp["embedding"]
    except Exception:
        return deterministic_embedding(text)
