"""
Unidade de trabalho do turno: dentro dele, o commit() de uma tool não efetiva
nada no banco; quem efetiva (ou desfaz) é a unidade.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import psycopg2
import pytest
from langchain.tools import tool
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from app.tools import connection
from app.tools.connection import unidade_do_turno, turno_atual, get_conn
from conftest import conta_eventos


# Tools de teste no mesmo padrão das reais: get_conn(), SQL, commit/rollback, close().
def tool_insere(marcador, fim="commit", pausa=0.0):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO events (title, start_time, source_text) VALUES ('t', now(), %s)",
            (marcador,),
        )
        time.sleep(pausa)
        if fim == "commit":
            conn.commit()
        elif fim == "rollback":
            conn.rollback()
    finally:
        cur.close()
        conn.close()


def tool_conta(marcador):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT count(*) FROM events WHERE source_text = %s", (marcador,))
        return cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()


def tool_com_sql_invalido():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM tabela_que_nao_existe")
        return {"status": "ok"}
    except psycopg2.Error as e:
        conn.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        cur.close()
        conn.close()


def test_fora_do_turno_get_conn_e_conexao_normal(banco):
    assert turno_atual() is None
    conn = get_conn()
    try:
        assert isinstance(conn, psycopg2.extensions.connection)
    finally:
        conn.close()


def test_commit_da_tool_nao_aparece_antes_de_confirmar(banco, marcador):
    with unidade_do_turno() as u:
        tool_insere(marcador)
        assert conta_eventos(marcador) == 0
        u.confirmar()
    assert conta_eventos(marcador) == 1


def test_sem_confirmar_nada_fica(banco, marcador):
    with unidade_do_turno():
        tool_insere(marcador)
    assert conta_eventos(marcador) == 0


def test_excecao_dentro_do_turno_desfaz(banco, marcador):
    with pytest.raises(RuntimeError):
        with unidade_do_turno():
            tool_insere(marcador)
            raise RuntimeError("orquestrador caiu")
    assert conta_eventos(marcador) == 0


def test_rollback_da_tool_desfaz_so_ela(banco, marcador):
    with unidade_do_turno() as u:
        tool_insere(marcador)
        tool_insere(marcador, fim="rollback")
        u.confirmar()
    assert conta_eventos(marcador) == 1


def test_close_sem_commit_descarta(banco, marcador):
    with unidade_do_turno() as u:
        tool_insere(marcador, fim=None)
        u.confirmar()
    assert conta_eventos(marcador) == 0


def test_erro_sql_numa_tool_nao_envenena_o_turno(banco, marcador):
    with unidade_do_turno() as u:
        tool_insere(marcador)
        assert tool_com_sql_invalido()["status"] == "error"
        tool_insere(marcador)
        u.confirmar()
    assert conta_eventos(marcador) == 2


def test_leitura_no_turno_ve_escrita_do_turno(banco, marcador):
    with unidade_do_turno():
        tool_insere(marcador)
        assert tool_conta(marcador) == 1


def test_turno_sem_banco_nao_abre_conexao():
    with unidade_do_turno() as u:
        pass
    assert u.usou_banco is False


def test_duas_tools_em_paralelo_serializam(banco, marcador):
    # A pausa entre o INSERT e o commit deixa as duas tools se cruzarem se não houver lock.
    with unidade_do_turno() as u:
        with ThreadPoolExecutor(2) as pool:
            futuros = [
                pool.submit(copy_context().run, tool_insere, marcador, "commit", 0.3)
                for _ in range(2)
            ]
            for futuro in futuros:
                futuro.result()
        u.confirmar()
    assert conta_eventos(marcador) == 2


def test_contextvar_chega_na_tool_pelo_toolnode(banco):
    @tool
    def ve_turno() -> str:
        """Diz se a tool enxerga a unidade do turno."""
        return str(turno_atual() is not None)

    # O ToolNode só roda com o runtime que o grafo dá; este grafo tem só ele.
    grafo = StateGraph(MessagesState)
    grafo.add_node("tools", ToolNode([ve_turno]))
    grafo.add_edge(START, "tools")
    grafo.add_edge("tools", END)

    chamada = {"name": "ve_turno", "args": {}, "id": "chamada-1", "type": "tool_call"}
    with unidade_do_turno():
        saida = grafo.compile().invoke({"messages": [AIMessage("", tool_calls=[chamada])]})
    resultado = saida["messages"][-1].content
    assert resultado == "True"


def test_commit_da_tool_marca_escreveu(banco, marcador):
    with unidade_do_turno() as u:
        assert u.escreveu is False
        tool_insere(marcador)
        assert u.escreveu is True


def test_leitura_nao_marca_escreveu(banco, marcador):
    with unidade_do_turno() as u:
        tool_conta(marcador)
        assert u.usou_banco is True
        assert u.escreveu is False


def test_tool_que_espera_demais_pelo_banco_recebe_timeout(banco, monkeypatch):
    monkeypatch.setattr(connection, "ESPERA_LOCK_S", 0.2)
    with unidade_do_turno():
        primeira = get_conn()  # segura o banco do turno até o close()
        try:
            with pytest.raises(TimeoutError):
                get_conn()
        finally:
            primeira.close()


def test_turno_parado_demais_e_desfeito_pelo_servidor(banco, marcador, monkeypatch):
    # Com 1 s no lugar de 120 s: o servidor encerra a sessão parada e desfaz a escrita.
    monkeypatch.setattr(connection, "IDLE_EM_TRANSACAO", "1s")
    with pytest.raises(psycopg2.Error):
        with unidade_do_turno() as u:
            tool_insere(marcador)
            time.sleep(2.5)
            u.confirmar()
    assert conta_eventos(marcador) == 0
