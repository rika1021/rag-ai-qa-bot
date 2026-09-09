from fastapi import APIRouter
from pydantic import BaseModel

from app.core.rag.generator import generate
from app.core.rag.retrieval import retrieve

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


@router.post("/")
def chat(body: ChatRequest):
    retrieval = retrieve(body.message)
    result = generate(body.message, retrieval)
    return result
