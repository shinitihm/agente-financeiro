import operator
from app.observabilidade import abrir_turno, fechar_turno, status_do_estado
from app.juiz import no_juiz
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, MessageGraph, END, MessagesState
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver
# from pg_tools import TOOLS
from langchain_groq import ChatGroq
from dotenv import load_dotenv
from datetime import datetime, timedelta
from langchain_community.vectorstores import FAISS
from app.guardrail import anonimizar_entrada, desanonimizar_saida,guardrail_entrada,guardrail_saida
from langchain_core.messages import RemoveMessage
import os
from time import sleep  
import yaml
from app.llm import faq_app,agenda_app,financeiro_app,router_app,orquestrador_app
from .prompts import(
    ROUTER_PROMPT_COMPLETO,
    FINANCEIRO_PROMPT_COMPLETO,
    AGENDA_PROMPT_COMPLETO,
    ORQUESTRADOR_PROMPT_COMPLETO,
    FAQ_PROMPT_COMPLETO
)
from app.tools.faq import faq_retriver
from app.memory import iniciar_sessao, salvar_mensagem, encerrar_sessao
import yaml

load_dotenv(dotenv_path=".env")

import os

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
CAMINHO_CONFIG = os.path.join(DIRETORIO_ATUAL, "config.yaml")
# 3. Abre usando o caminho completo
with open(CAMINHO_CONFIG, "r", encoding="utf-8") as file:
    config = yaml.safe_load(file)


    

# =========================================================
# LOOP PRINCIPAL
# =========================================================
print("\033[031m\tChat iniciado. Digite 'sair' para encerrar.\033[0m\n")


# ==============================================================================
# ESTADO
# ==============================================================================
class Estado(MessagesState):
    agentes_chamados: Annotated[list[str], operator.add]
    rota: str                                      # resposta para o usuário
    mapa_pii: dict
# ==============================================================================
# NÓS
# ==============================================================================
def no_roteador(estado: Estado) -> dict:
    # CORREÇÃO 1: Passar as mensagens diretamente do estado
    saida = router_app.invoke(
        {"messages": estado["messages"]}, 
    )
    
    texto = saida["messages"][-1].content
    rota = 'fim'
    
    # Resposta direta (saudação, fora de escopo):
    if "ROUTE=" not in texto:
        return {
            "agentes_chamados": ["roteador"],
            "rota"            :  rota,
            # CORREÇÃO 2: Passar como tupla ('ai', texto)
            "messages"        : [("ai", saida['messages'][-1].content)], 
        }
        
    for linha in texto.splitlines():
        if linha.startswith("ROUTE="):
            rota = linha.split("=", 1)[1].strip()
            break

    # Encaminhamento: sobrescreve input com o protocolo para o especialista
    return {

        "agentes_chamados": ["roteador"],
        "rota": rota,
        "messages": [{"role": "human", "content": texto}],
    }

def no_orquestrador(estado: Estado) -> dict:
    ultimo_especialista = ''
    #PEGAR A ULTIMA MENSAGEM GARANTINDO QUE SEJA DE IA
    for mensagem in reversed(estado["messages"]):
        if mensagem.type == "ai" and mensagem.content:
            ultimo_especialista = mensagem.content
            break

    #PEGAR A ULTIMA MENSAGEM GERAL(MAS TEM O RISCO DE N SER DE IA)
    saida = orquestrador_app.invoke(
    {"messages": [{"role":"human","content":ultimo_especialista}]},
    )

    #content ultima
    return {
        "agentes_chamados": [estado["rota"],"orquestrador"],
        "messages": [("assistant", saida['messages'][-1].content)]
    }


# ==============================================================================
# FUNÇÃO DE DECISÃO
# ==============================================================================
def decidir_especialista(estado: Estado) -> str:
    """Lê o protocolo do roteador e devolve o nome do próximo nó."""
    return estado['rota'] if estado['rota'] in ("financeiro", "agenda", "faq") else "fim"
 
def no_guardrail_entrada(estado: Estado) -> dict:
    human_message = list(estado["messages"])[-1]  # Pega a última mensagem do usuário
    texto_anon,mapa_pii = anonimizar_entrada(texto=estado['messages'][-1].content) 
    resultado = guardrail_entrada(texto_anon)
    #colocar os agentes chamados, é uma lista de string
    if resultado['bloqueado'] == True:
         return {
            "messages":         [{"role": "assistant", "content": resultado["mensagem"]}],
            "rota":             END,
            "agentes_chamados": [f"guardrail_entrada:{resultado['motivo']}"],
        }
    return {
        "messages": [
            RemoveMessage(id=human_message.id),          # remove a original pelo id
            {"role": "human", "content": texto_anon}, # adiciona a anonimizada
        ],
        "mapa_pii":         mapa_pii,
        "agentes_chamados": ["guardrail_entrada:aprovado"],
        "rota":             "",
    }

def no_guardrail_saida(estado: Estado) -> dict:
    ultima =""
    for msg in reversed(estado["messages"]):
        if msg.type == 'ai' and msg.content:
            ultima = msg.content
            break
    
    resultado = guardrail_saida(ultima, estado['mapa_pii'], {})

    return {"messages":         [{"role": "assistant", "content": resultado["conteudo"]}],
            "agentes_chamados": ["guardrail_saida"]}

def decidir_pos_guardrail_entrada(estado: Estado) -> str:
    """Lê o protocolo do guardrail e devolve o próximo nó."""
    return estado["rota"] if estado["rota"] == "fim" else "fim"

# ==============================================================================
# CONSTRUÇÃO DO GRAFO
# ==============================================================================
grafo = StateGraph(Estado)  

grafo.add_node("roteador",     no_roteador)
grafo.add_node("financeiro",   financeiro_app)
grafo.add_node("agenda",       agenda_app)
grafo.add_node("faq",          faq_app)
grafo.add_node("orquestrador", no_orquestrador)
grafo.add_node("guardrail_entrada", no_guardrail_entrada)
grafo.add_node("guardrail_saida", no_guardrail_saida)
grafo.add_node("juiz", no_juiz)



grafo.set_entry_point("roteador")

grafo.add_conditional_edges(
    "roteador",
    decidir_especialista,
    {
        "financeiro": "financeiro",
        "agenda":     "agenda",
        "faq":        "faq",
        "fim":        END,       # resposta direta: sem especialista nem orquestrador
    },
)

grafo.add_conditional_edges(
    "guardrail_entrada",
    decidir_pos_guardrail_entrada,
    {"roteador":"roteador",
     'fim':END}
)

grafo.add_edge("financeiro",      "orquestrador")
grafo.add_edge("agenda",          "orquestrador")
grafo.add_edge("orquestrador",    "guardrail_saida")
grafo.add_edge("guardrail_saida", "juiz")
grafo.add_edge("faq",             "juiz")
grafo.add_edge("juiz",            END)

# Memória centralizada no grafo — persiste o Estado inteiro entre turns
memory = MemorySaver()
fluxo_agentes = grafo.compile(checkpointer=memory)


# ==============================================================================
# FLUXO PRINCIPAL
# ==============================================================================
def executar_fluxo_assessor(
    pergunta_usuario: str, session_id: str, user_id: str = "usuario_teste"
) -> tuple[str, list[str]]:
    pergunta_usuario_anonimizado, _ = anonimizar_entrada(pergunta_usuario)
    estado_inicial = {
        "messages":         [{"role": "human", "content": pergunta_usuario}],
        "agentes_chamados": [],
        "rota":             "",
        "mapa_pii":         {},
        "session_id":       session_id,

    }

    # O registro abre antes do invoke e fecha no finally, inclusive quando
    # o grafo levanta. A rota /monitor só lê o que ficou anotado.
    turno_id = abrir_turno()
    status = "erro"
    rota = ""
    try:
        config = {
            "configurable": {"thread_id": session_id, "user_id": user_id},
            # LangSmith: nome, tags e metadata do trace raiz (session_id agrupa em Threads)
            "run_name": "assessor_turno",
            "tags": ["assessor", "fastapi"],
            "metadata": {"session_id": session_id, "user_id": user_id, "turno_id": turno_id},
        }
        # agentes_chamados acumula entre turnos da mesma sessão (reducer + checkpointer);
        # guarda o tamanho anterior para devolver só os agentes deste turno.
        n_anteriores = len(fluxo_agentes.get_state(config).values.get("agentes_chamados", []))
        estado_final = fluxo_agentes.invoke(estado_inicial, config=config)

        resposta = estado_final["messages"][-1].text

        # Salva no MongoDB após cada interação
        salvar_mensagem(session_id, "human",     pergunta_usuario_anonimizado)
        salvar_mensagem(session_id, "assistant", resposta)

        status = status_do_estado(estado_final)
        rota = estado_final.get("rota") or ""
        return resposta, estado_final["agentes_chamados"][n_anteriores:]
    finally:
        fechar_turno(turno_id, session_id=session_id, rota=rota, status=status)
#controle de sessão
session_id = "session_1"
iniciar_sessao(session_id=session_id)

# while True:
#     user_input = input("> ").strip()

#     if user_input.lower() in ("sair", "fim", "end", "tchau", "bye","flw"):
#         print("\033[034mEncerrando a conversa...\033[0m")
#         break
#     elif user_input.lower() in ("taiwan não é um país","não gosto do meu xiomi","não gosto do professor grilo"):
#         print("\tO QUE??\n\033[031mvocê está maluco?\033[0m")
#         sleep(1)
#         print("\tadeus...")
#         break

#     try:
#         resposta = executar_fluxo_assessor(
#             pergunta_usuario=user_input,
#             session_id=session_id)
#         print("-" * 50)
#         print(resposta)

#     except Exception as e:
#         print(f"\033[031mErro: \033[0m{e}")