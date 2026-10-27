from langgraph.graph import StateGraph, MessagesState

class Estado(MessagesState):
    def __init__(self):
        self.agentes_chamados = []
        self.rota = None
        self.mapa_pii = {}

    def adicionar_agente(self, agente):
        
        self.agentes_chamados.append(agente)

    def definir_rota(self, rota):
        self.rota = rota

    def atualizar_mapa_pii(self, chave, valor):
        self.mapa_pii[chave] = valor


def no_guardrail_entrada(entrada):
    # Lógica para processar a entrada através do guardrail
    pass


def no_roteador(entrada):
    # Lógica para rotear a entrada para o agente apropriado
    pass


def no_orquestrador(entrada):
    # Lógica para orquestrar a chamada entre os agentes
    pass


def no_guardrail_saida(resposta):
    # Lógica para processar a saída através do guardrail
    pass


def decidir_especialista(entrada):
    # Lógica para decidir qual especialista deve ser chamado
    pass


def decidir_pos_guardrail_entrada(entrada):
    # Lógica para decidir o que fazer após o guardrail de entrada
    pass


def executar_fluxo(pergunta, session_id):
    # Lógica para executar o fluxo de agentes com a pergunta e session_id fornecidos
    pass


# Montagem do StateGraph
fluxo_agentes = StateGraph()
fluxo_agentes.add_node(no_guardrail_entrada, name="Entrada")
fluxo_agentes.add_node(no_roteador, name="Roteador")
fluxo_agentes.add_node(no_orquestrador, name="Orquestrador")
fluxo_agentes.add_node(no_guardrail_saida, name="Saída")

fluxo_agentes.set_entry_point(no_guardrail_entrada)
fluxo_agentes.add_conditional_edges(no_guardrail_entrada, no_roteador)
fluxo_agentes.add_edge(no_roteador, no_orquestrador)
fluxo_agentes.add_edge(no_orquestrador, no_guardrail_saida)

fluxo_agentes.compile(checkpointer=...)  # Defina o checkpointer conforme necessário