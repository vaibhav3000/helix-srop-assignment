import argparse
import asyncio
import hashlib
import re
from pathlib import Path

import chromadb
import google.generativeai as genai

from app.settings import settings


# pull out YAML frontmatter if present
def extract_metadata_and_text(text: str) -> tuple[dict, str]:
    """Extracts YAML frontmatter from the beginning of a markdown document.

    Args:
        text: The raw text of the markdown file.

    Returns:
        A tuple containing a dictionary of extracted metadata (if any) and the remaining text.
    """
    metadata = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    metadata[key.strip()] = val.strip()
            text = parts[2]
    return metadata, text


# split at markdown headings; sub-split big sections by sentence
def chunk_markdown(text: str, max_tokens: int = 400) -> list[str]:
    """Splits markdown text into logical chunks based on headings and sentence boundaries.

    Args:
        text: The markdown text to be chunked.
        max_tokens: The target maximum token limit per chunk.

    Returns:
        A list of string chunks, ideally preserving logical markdown sections.
    """
    max_chars = max_tokens * 4  # ~4 chars per token

    heading_chunks = re.split(r'\n(?=#{1,2} )', text)

    final_chunks = []
    for chunk in heading_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        if len(chunk) <= max_chars:
            final_chunks.append(chunk)
            continue

        # section too big — break at sentence boundaries
        sentences = chunk.split(". ")
        current: list[str] = []
        current_len = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if not sentence.endswith("."):
                sentence += "."

            if current_len + len(sentence) > max_chars and current:
                final_chunks.append(" ".join(current))
                current = [sentence]
                current_len = len(sentence)
            else:
                current.append(sentence)
                current_len += len(sentence)

        if current:
            final_chunks.append(" ".join(current))

    return final_chunks


# index all markdown files in the given directory
async def ingest_directory(docs_path: Path) -> None:
    """Recursively reads markdown files from a directory, chunks them, generates embeddings, and upserts them into ChromaDB.

    Args:
        docs_path: A pathlib.Path object representing the directory to scan for .md files.
    """
    md_files = list(docs_path.rglob("*.md"))

    if settings.GOOGLE_API_KEY:
        genai.configure(api_key=settings.GOOGLE_API_KEY)

    chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
    collection = chroma_client.get_or_create_collection(name="helix_docs")

    total_chunks = 0

    for file_path in md_files:
        raw_text = file_path.read_text(encoding="utf-8")
        metadata, text = extract_metadata_and_text(raw_text)
        chunks = chunk_markdown(text)

        chunk_ids, embeddings, documents, metadatas = [], [], [], []

        for i, chunk in enumerate(chunks):
            # Generate a stable, deterministic ID for each chunk based on its source file and index
            chunk_id = hashlib.sha256(f"{file_path}::{i}".encode()).hexdigest()[:12]

            # embed or use a dummy vector if no key set
            if settings.GOOGLE_API_KEY:
                resp = genai.embed_content(
                    model=settings.EMBED_MODEL,
                    content=chunk,
                    task_type="retrieval_document",
                )
                embedding = resp["embedding"]
            else:
                embedding = [0.1] * 768

            chunk_ids.append(chunk_id)
            embeddings.append(embedding)
            documents.append(chunk)
            chunk_meta = {"source": str(file_path), "chunk_index": i}
            chunk_meta.update(metadata)
            metadatas.append(chunk_meta)

        if chunk_ids:
            collection.upsert(
                ids=chunk_ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )

        total_chunks += len(chunks)

    print(f"Ingest done: {len(md_files)} files, {total_chunks} chunks upserted.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest docs into the vector store")
    parser.add_argument("--path", type=Path, required=True, help="Directory containing .md files")
    args = parser.parse_args()
    asyncio.run(ingest_directory(args.path))


if __name__ == "__main__":
    main()
