from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    session_id: str = Field(..., description="The ID of the chat session")
    user_id: str = Field("usuario_teste", description="The ID of the user making the request")
    pergunta: str = Field(..., description="The message content from the user")

class ChatResponse(BaseModel):
    agentes_chamados: list[str] = Field(..., description="List of agents called during the chat")
    resposta: str = Field(..., description="The response message from the assistant")

class SessionResponse(BaseModel):
    session_id: str = Field(..., description="The ID of the chat session")
    resumo: str = Field("", description="Summary generated when the session is closed")
