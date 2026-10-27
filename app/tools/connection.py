"""
Conexão das tools com o Postgres.

Fora de um turno do Assessor (servidor MCP, scripts), get_conn() devolve uma
conexão psycopg2 comum, e o commit() da tool efetiva na hora.

Dentro de um turno (unidade_do_turno()), as tools dividem uma transação só.
O commit() de cada tool fecha apenas o trecho dela, num savepoint. Quem decide
se o turno fica no banco é o nó efetivar, depois do veredito do juiz.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator

import psycopg2

from app.config import DATABASE_URL

# Quanto uma tool espera outra do mesmo turno largar a conexão.
ESPERA_LOCK_S = 30
# Turno parado além disso (processo travou) é encerrado e desfeito pelo servidor.
IDLE_EM_TRANSACAO = "120s"


def _conectar():
    if not DATABASE_URL:
        raise ValueError("A variável DATABASE_URL não foi encontrada no .env")
    return psycopg2.connect(DATABASE_URL)


class UnidadeDoTurno:
    """A transação do turno. A conexão só abre no primeiro get_conn()."""

    def __init__(self) -> None:
        self._conn = None
        self._lock = threading.Lock()
        self._savepoints = 0
        self.escreveu = False
        self.efeitos_pos_commit: list[Callable[[], dict]] = []

    @property
    def usou_banco(self) -> bool:
        return self._conn is not None

    def _executar(self, *comandos: str) -> None:
        # Uma ida ao servidor para todos os comandos: cada ida ao Aiven soma
        # na latência do turno.
        with self._conn.cursor() as cur:
            cur.execute("; ".join(comandos))

    def conexao_da_tool(self) -> _ConexaoDaTool:
        # O ToolNode roda as tools de uma mesma resposta em paralelo, e uma
        # conexão psycopg2 não aguenta dois savepoints intercalados.
        if not self._lock.acquire(timeout=ESPERA_LOCK_S):
            raise TimeoutError("Outra tool do turno ainda está usando o banco.")
        try:
            comandos = []
            if self._conn is None:
                self._conn = _conectar()
                comandos.append(f"SET idle_in_transaction_session_timeout = '{IDLE_EM_TRANSACAO}'")
            self._savepoints += 1
            savepoint = f"tool_{self._savepoints}"
            self._executar(*comandos, f"SAVEPOINT {savepoint}")
        except BaseException:
            self._lock.release()
            raise
        return _ConexaoDaTool(self, savepoint)

    def confirmar(self) -> None:
        """COMMIT do turno. Se falhar, a exceção sobe para quem chamou."""
        if self._conn is not None:
            self._conn.commit()

    def desfazer(self) -> None:
        """ROLLBACK do turno. Chamar de novo não tem efeito."""
        if self._conn is not None and not self._conn.closed:
            self._conn.rollback()

    def fechar(self) -> None:
        if self._conn is not None:
            self._conn.close()


class _ConexaoDaTool:
    """O que a tool recebe de get_conn() dentro do turno."""

    def __init__(self, unidade: UnidadeDoTurno, savepoint: str) -> None:
        self._unidade = unidade
        self._savepoint = savepoint
        self._fechada = False

    def cursor(self, *args, **kwargs):
        # Cursor da conexão real: leituras do turno enxergam as escritas do turno.
        return self._unidade._conn.cursor(*args, **kwargs)

    def commit(self) -> None:
        # O efeito fica na transação do turno, não no banco. O savepoint novo
        # protege o que a tool fizer depois (o SELECT do update_transaction).
        self._unidade._executar(f"RELEASE SAVEPOINT {self._savepoint}", f"SAVEPOINT {self._savepoint}")
        self._unidade.escreveu = True

    def rollback(self) -> None:
        # Desfaz só esta tool, não as anteriores do turno.
        self._unidade._executar(f"ROLLBACK TO SAVEPOINT {self._savepoint}")

    def close(self) -> None:
        # Como no psycopg2: fechar sem commit descarta o que não foi confirmado,
        # e limpa um estado de transação abortada.
        if self._fechada:
            return
        self._fechada = True
        self._unidade._executar(f"ROLLBACK TO SAVEPOINT {self._savepoint}", f"RELEASE SAVEPOINT {self._savepoint}")
        self._unidade._lock.release()


# Uma ContextVar, e não threading.local: o ToolNode roda as tools em outra
# thread, com copy_context(). O valor é posto antes do invoke e é um objeto
# mutável, então todas as cópias do contexto apontam para a mesma unidade.
_turno: ContextVar[UnidadeDoTurno | None] = ContextVar("unidade_do_turno", default=None)


def turno_atual() -> UnidadeDoTurno | None:
    return _turno.get()


def get_conn():
    unidade = _turno.get()
    if unidade is None:
        return _conectar()
    return unidade.conexao_da_tool()


@contextmanager
def unidade_do_turno() -> Iterator[UnidadeDoTurno]:
    """Abre o turno para as tools. Na saída, desfaz o que não foi confirmado e fecha."""
    unidade = UnidadeDoTurno()
    token = _turno.set(unidade)
    try:
        yield unidade
    finally:
        _turno.reset(token)
        try:
            unidade.desfazer()
        finally:
            unidade.fechar()
