import argparse
import asyncio
import hashlib
import re
from pathlib import Path

import chromadb
import google.generativeai as genai

from app.settings import settings


def extract_metadata_and_text(text: str) -> tuple[dict, str]:
    """
    Extract metadata from a markdown file's frontmatter.
    Returns a tuple of (metadata_dict, remaining_text).
    """
    metadata = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            text = parts[2]
            for line in frontmatter.strip().split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    metadata[key.strip()] = val.strip()
    return metadata, text


def chunk_markdown(text: str, max_tokens: int = 400) -> list[str]:
    """
    Split document into chunks by heading boundaries (# or ##).
    Then sub-split any chunk exceeding max_tokens (~4 chars per token) by sentence.
    """
    # Rough estimate: 1 token = 4 characters
    max_chars = max_tokens * 4
    
    # Split by heading boundaries
    heading_chunks = re.split(r'\n(?=#{1,2} )', text)
    
    final_chunks = []
    for chunk in heading_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
            
        if len(chunk) <= max_chars:
            final_chunks.append(chunk)
        else:
            # Sub-split by sentence
            sentences = chunk.split(". ")
            current_chunk = []
            current_len = 0
            
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                    
                # Add period back if missing
                if not sentence.endswith("."):
                    sentence += "."
                    
                if current_len + len(sentence) > max_chars and current_chunk:
                    final_chunks.append(" ".join(current_chunk))
                    current_chunk = [sentence]
                    current_len = len(sentence)
                else:
                    current_chunk.append(sentence)
                    current_len += len(sentence)
            
            if current_chunk:
                final_chunks.append(" ".join(current_chunk))
                
    return final_chunks


async def ingest_directory(docs_path: Path) -> None:
    """
    Walk docs_path, chunk and embed every .md file, upsert into vector store.
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
        
        chunk_ids = []
        embeddings = []
        documents = []
        metadatas = []
        
        for i, chunk in enumerate(chunks):
            chunk_id = hashlib.sha256(f"{file_path}::{i}".encode()).hexdigest()[:12]
            
            # Embed chunk
            if settings.GOOGLE_API_KEY:
                # In a real scenario, we might batch these
                response = genai.embed_content(
                    model=settings.EMBED_MODEL,
                    content=chunk,
                    task_type="retrieval_document"
                )
                embedding = response['embedding']
            else:
                # Mock embedding for local testing if no API key
                embedding = [0.1] * 768
                
            chunk_ids.append(chunk_id)
            embeddings.append(embedding)
            documents.append(chunk)
            
            chunk_metadata = {"source": str(file_path), "chunk_index": i}
            chunk_metadata.update(metadata)
            metadatas.append(chunk_metadata)
            
        if chunk_ids:
            collection.upsert(
                ids=chunk_ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
            
        total_chunks += len(chunks)
        
    print(f"Ingest complete: {len(md_files)} files, {total_chunks} chunks upserted.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest docs into the vector store")
    parser.add_argument("--path", type=Path, required=True, help="Directory containing .md files")
    args = parser.parse_args()

    asyncio.run(ingest_directory(args.path))


if __name__ == "__main__":
    main()
