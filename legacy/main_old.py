import operator
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, MessageGraph, END, MessagesState
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver
from pg_tools import TOOLS
from langchain_groq import ChatGroq
from dotenv import load_dotenv
from datetime import datetime, timedelta
from langchain_community.vectorstores import FAISS
from guardrail import anonimizar_entrada, desanonimizar_saida,guardrail_entrada,guardrail_saida
from langchain_core.messages import RemoveMessage
import os
from time import sleep  
import yaml
from prompts import(
    ROUTER_PROMPT_COMPLETO,
    FINANCEIRO_PROMPT_COMPLETO,
    AGENDA_PROMPT_COMPLETO,
    ORQUESTRADOR_PROMPT_COMPLETO,
    FAQ_PROMPT_COMPLETO
)
from faq_tools import faq_retriver
from memory_mongodb import iniciar_sessao, salvar_mensagem, encerrar_sessao
import yaml

load_dotenv(dotenv_path=".env")

import os

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
CAMINHO_CONFIG = os.path.join(DIRETORIO_ATUAL, "config.yaml")
# 3. Abre usando o caminho completo
with open(CAMINHO_CONFIG, "r", encoding="utf-8") as file:
    config = yaml.safe_load(file)


    
# =========================================================
# MODELOS
# =========================================================
llm_gemini = ChatGoogleGenerativeAI(
    model=config["Agent_Model"]['gemini_flash'],
    google_api_key=os.getenv("GEMINI_API_KEY"),
    temperature=0.2,
    top_p=0.9
)

llm_groq = ChatGroq(
    model=config["Agent_Model"]['groq_llama'],
    temperature=0.2,
    api_key=os.getenv("GROQ_API_KEY")
)

llm_especialista = llm_gemini.with_fallbacks([llm_groq])
llm_rapido = ChatGroq(
    model=config["Agent_Model"]['groq_llama'],
    temperature=0.0,
    api_key=os.getenv("GROQ_API_KEY")
)

router_memory=MemorySaver()

# =========================================================
# AGENTE
# =========================================================

# ROTEADOR:
router_app =create_agent(
  model=llm_rapido,
  system_prompt=ROUTER_PROMPT_COMPLETO,
  checkpointer=router_memory
)

#FAQ
faq_app = create_agent(
    model=llm_rapido,
    system_prompt=FAQ_PROMPT_COMPLETO,
    tools=[faq_retriver]
)

#ESPECIALISTAS:
#FINANCEIRO
financeiro_app = create_agent(
  model=llm_especialista,
  tools=TOOLS,
  system_prompt=FINANCEIRO_PROMPT_COMPLETO,
)
#O DE AGENDA
agenda_app = create_agent(
  model=llm_especialista,
  system_prompt=AGENDA_PROMPT_COMPLETO,
)

#ORQUESTRADOR 
orquestrador_app =create_agent(
  model=llm_rapido,
  system_prompt=ORQUESTRADOR_PROMPT_COMPLETO,
)
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
        "rota": "fim",
        "messages": [{"role": "assistant", "content": texto}],
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

def no_guardrail_saida(estado: Estado) -> dict:

    resultado = guardrail_saida(estado["messages"][-1].text, estado.get("mapa_pii", {}))

    return {
        "messages":         [{"role": "assistant", "content": resultado["mensagem"]}],
        "agentes_chamados": ["guardrail_saida"],
    }

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

grafo.add_conditional_edges(
    "guardrail_saida",
    guardrail_saida,
    {"roteador":"roteador",
     'fim':END}
)

grafo.add_edge("financeiro",   "orquestrador")
grafo.add_edge("agenda",       "orquestrador")
grafo.add_edge("orquestrador", END)
grafo.add_edge("faq",          END)   # FAQ bypassa o orquestrador

# Memória centralizada no grafo — persiste o Estado inteiro entre turns
memory = MemorySaver()
fluxo_agentes = grafo.compile(checkpointer=memory)


# ==============================================================================
# FLUXO PRINCIPAL
# ==============================================================================
def executar_fluxo_assessor(pergunta_usuario: str, session_id: str) -> str:
    estado_inicial = {
        "messages": [{"role": "human", "content": pergunta_usuario}],
        "agentes_chamados": [],
        "rota": "",
        "mapa_pii":{}
    }

    estado_final = fluxo_agentes.invoke(
        estado_inicial,
        config={"configurable": {"thread_id": session_id}},
    )

    print(f"[debug] agentes chamados: {estado_final['agentes_chamados']}")
    return estado_final["messages"][-1].content
#controle de sessão
session_id = "session_1"
iniciar_sessao(session_id=session_id)
while True:
    user_input = input("> ").strip()

    if user_input.lower() in ("sair", "fim", "end", "tchau", "bye","flw"):
        print("\033[034mEncerrando a conversa...\033[0m")
        break
    elif user_input.lower() in ("taiwan não é um país","não gosto do meu xiomi","não gosto do professor grilo"):
        print("\tO QUE??\n\033[031mvocê está maluco?\033[0m")
        sleep(1)
        print("\tadeus...")
        break

    try:
        resposta = executar_fluxo_assessor(
            pergunta_usuario=user_input,
            session_id=session_id)
        print("-" * 50)
        print(resposta)

    except Exception as e:
        print(f"\033[031mErro: \033[0m{e}")