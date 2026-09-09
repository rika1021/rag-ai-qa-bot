from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.core.config import settings
from app.core.vectorstore import embed, get_collection


def _load_document(file_path: Path) -> str:
    if file_path.suffix.lower() == ".pdf":
        reader = PdfReader(str(file_path))
        # 頁間用 \n\n 分隔，讓 _semantic_chunk 能正確識別段落邊界
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    return file_path.read_text(encoding="utf-8")


def _semantic_chunk(text: str) -> list[str]:
    max_size = settings.chunk_size    # 500
    overlap = settings.chunk_overlap  # 50
    min_paragraph = 80

    raw_paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    merged: list[str] = []
    buffer = ""
    for para in raw_paragraphs:
        if not buffer:
            buffer = para
        elif len(buffer) < min_paragraph and len(buffer) + len(para) <= max_size:
            buffer = buffer + "\n\n" + para
        else:
            merged.append(buffer)
            buffer = para
    if buffer:
        merged.append(buffer)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_size, chunk_overlap=overlap
    )
    final_chunks: list[str] = []
    for para in merged:
        if len(para) > max_size:
            final_chunks.extend(splitter.split_text(para))
        else:
            final_chunks.append(para)

    return final_chunks


def _make_chunk_id(filename: str, index: int) -> str:
    return f"{filename}_chunk_{index}"


def ingest_document(file_path: Path) -> int:
    raw_text = _load_document(file_path)
    chunks = _semantic_chunk(raw_text)

    if not chunks:
        return 0

    filename = file_path.name
    ids = [_make_chunk_id(filename, i) for i in range(len(chunks))]
    metadatas = [{"source": filename, "chunk_index": i} for i in range(len(chunks))]
    embeddings = embed(chunks)

    collection = get_collection()

    existing = collection.get(where={"source": filename})
    if existing["ids"]:
        collection.delete(where={"source": filename})

    collection.add(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    return len(chunks)


def delete_document(filename: str) -> None:
    collection = get_collection()
    collection.delete(where={"source": filename})


def list_documents() -> list[str]:
    collection = get_collection()
    result = collection.get(include=["metadatas"])
    seen: set[str] = set()
    for meta in result["metadatas"]:
        seen.add(meta["source"])
    return sorted(seen)
