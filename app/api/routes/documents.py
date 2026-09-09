from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.rag.ingestion import delete_document, ingest_document, list_documents

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}


@router.post("/upload")
async def upload_document(file: UploadFile):
    suffix = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支援的檔案格式：{suffix}。支援格式：{', '.join(ALLOWED_EXTENSIONS)}",
        )

    dest = settings.data_dir / file.filename
    contents = await file.read()
    dest.write_bytes(contents)

    chunks = ingest_document(dest)

    return {"filename": file.filename, "chunks": chunks}


@router.get("/")
def get_documents():
    return {"documents": list_documents()}


@router.delete("/{filename}")
def remove_document(filename: str):
    file_path = settings.data_dir / filename
    if file_path.exists():
        file_path.unlink()

    delete_document(filename)

    return JSONResponse(content={"message": f"{filename} 已從知識庫移除"})
