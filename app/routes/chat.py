from fastapi import APIRouter 
from langchain_google_genai import ChatGoogleGenerativeAI
from app.config import OBRIGATORIAS
from app.schemas import ChatRequest, ChatResponse
from app.llm import llm_especialista,llm_gemini,llm_groq,llm_gemini
from app.graph import executar_fluxo_assessor
router = APIRouter(tags=['chat'])

@router.post('/chat')
def conversar(requisicao:ChatRequest) -> ChatResponse:
    resposta, agentes_chamados = executar_fluxo_assessor(requisicao.pergunta, requisicao.session_id, requisicao.user_id)

    chat = ChatResponse(agentes_chamados=agentes_chamados, resposta=resposta)

    return chat