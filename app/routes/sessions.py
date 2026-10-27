import uuid
from fastapi import APIRouter
from app.schemas import SessionResponse
from app.memory import iniciar_sessao, encerrar_sessao, recuperar_historico

router = APIRouter(prefix='/sessions', tags=['sessions'])

@router.post('')
def criar_sessao() -> SessionResponse:
    session_id = str(uuid.uuid4())
    iniciar_sessao(session_id)
    return SessionResponse(session_id=session_id)

@router.delete('/{session_id}')
def finalizar_sessao(session_id: str) -> SessionResponse:
    resumo = encerrar_sessao(session_id)
    return SessionResponse(session_id=session_id, resumo=resumo)

@router.get('/{session_id}/historico')
def historico(session_id: str, busca: str = "", limite: int = 3) -> list[dict]:
    return recuperar_historico(session_id, busca, limite)
