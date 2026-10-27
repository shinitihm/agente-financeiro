from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langchain_groq import ChatGroq
from app.tools.pg_tools import TOOLS
from app.tools.agenda import TOOLS_GOOGLE
from datetime import datetime, timedelta
from langchain_community.vectorstores import FAISS
from langchain_core.messages import RemoveMessage
import os
from time import sleep  
import yaml
from app.prompts import(
    ROUTER_PROMPT_COMPLETO,
    FINANCEIRO_PROMPT_COMPLETO,
    AGENDA_PROMPT_COMPLETO,
    ORQUESTRADOR_PROMPT_COMPLETO,
    FAQ_PROMPT_COMPLETO
)
from app.tools.faq import faq_retriver
import yaml
from app.config import OBRIGATORIAS

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
CAMINHO_CONFIG = os.path.join(DIRETORIO_ATUAL, "config.yaml")
# 3. Abre usando o caminho completo
with open(CAMINHO_CONFIG, "r", encoding="utf-8") as file:
    config = yaml.safe_load(file)


# MODELOS
llm_gemini = ChatGoogleGenerativeAI(
    model=config["Agent_Model"]['gemini_flash'],
    google_api_key=OBRIGATORIAS["GEMINI_API_KEY"],
    temperature=0.2,
    top_p=0.9
)

llm_groq = ChatGroq(
    model=config["Agent_Model"]['groq_llama'],
    temperature=0.2,
    api_key=OBRIGATORIAS["GROQ_API_KEY"]
)

llm_especialista = llm_gemini.with_fallbacks([llm_groq])
llm_rapido = ChatGroq(
    model=config["Agent_Model"]['groq_llama'],
    temperature=0.0,
    api_key=OBRIGATORIAS["GROQ_API_KEY"]
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
  tools=TOOLS_GOOGLE,
  system_prompt=AGENDA_PROMPT_COMPLETO,
)

#ORQUESTRADOR 
orquestrador_app =create_agent(
  model=llm_rapido,
  system_prompt=ORQUESTRADOR_PROMPT_COMPLETO,
)