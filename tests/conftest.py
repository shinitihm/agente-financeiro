"""
Fixtures dos testes.

O banco é o Postgres do .env. Cada teste grava com um marcador próprio em
source_text e o teardown apaga só as linhas desse marcador.
"""
import sys
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.config import DATABASE_URL  # noqa: E402
from app.tools.connection import get_conn  # noqa: E402

# Uma conexão só para conferir e limpar, aberta uma vez: com o Aiven, cada
# conexão nova custa uns 2-3 s.
_fora = None


def _conexao_de_fora():
    """Não passa pelo turno e está em autocommit: cada consulta vê só o que foi efetivado."""
    global _fora
    if _fora is None or _fora.closed:
        _fora = psycopg2.connect(DATABASE_URL)
        _fora.autocommit = True
    return _fora


def pytest_sessionfinish(session, exitstatus):
    if _fora is not None:
        _fora.close()


def conta_eventos(marcador: str) -> int:
    with _conexao_de_fora().cursor() as cur:
        cur.execute("SELECT count(*) FROM events WHERE source_text = %s", (marcador,))
        return cur.fetchone()[0]


@pytest.fixture(scope="session")
def banco():
    try:
        conn = get_conn()
    except Exception:
        pytest.skip("Postgres indisponível")
    yield conn
    conn.close()


@pytest.fixture
def marcador():
    valor = f"teste-{uuid4()}"
    yield valor
    with _conexao_de_fora().cursor() as cur:
        cur.execute("DELETE FROM events WHERE source_text = %s", (valor,))
