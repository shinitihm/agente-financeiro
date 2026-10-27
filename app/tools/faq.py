from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.tools import tool
from langchain_community.vectorstores import FAISS

import os
from app.prompts import(
    ROUTER_PROMPT_COMPLETO,
    FINANCEIRO_PROMPT_COMPLETO,
    AGENDA_PROMPT_COMPLETO,
    ORQUESTRADOR_PROMPT_COMPLETO,
    FAQ_PROMPT_COMPLETO
)
from app.config import FAQ_PDF_PATH as PDF_PATH
from app.config import OBRIGATORIAS

@tool
def faq_retriver(question: str):
    """Use esta ferramenta para buscar informações e responder dúvidas no FAQ da assessoria."""
    #leitura do doc
    loader = PyPDFLoader(PDF_PATH)
    docs = loader.load()

    #pre processamento dos dados, normaliza, remove ruidos e prepara o texto
    splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=150)
    chunks = splitter.split_documents(docs)

    embeddings = GoogleGenerativeAIEmbeddings(
        model ='gemini-embedding-2-preview',
        google_api_key=OBRIGATORIAS("GEMINI_API_KEY")
    )

    #FAIIS VECTOR DB
    db = FAISS.from_documents(      chunks, embeddings)

    #RECUPERACAO DE CONTEXTO
    results = db.similarity_search(question, k=6) 
    
    return results