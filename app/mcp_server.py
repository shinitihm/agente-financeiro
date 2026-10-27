"""
Servidor MCP do financeiro. Expõe as mesmas tools que o financeiro_app usa
(app/tools/pg_tools.py), então o SQL vive num lugar só.
"""
import sys
from pathlib import Path
from typing import Annotated, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from app.tools.pg_tools import (
    add_transaction as _add_transaction,
    daily_balance as _daily_balance,
    query_transactions as _query_transactions,
    total_balance as _total_balance,
    update_transaction as _update_transaction,
)

mcp = MCPServer(
    name="assessor-financeiro",
    version="1.0.0",
    instructions="Ferramentas financeiras do Assessor.AI...",
)

LEITURA = ToolAnnotations(readOnlyHint=True)
ESCRITA = ToolAnnotations(readOnlyHint=False, destructiveHint=False)


def _chamar(tool, **argumentos) -> dict[str, Any]:
    # Repassa só o que veio preenchido, para valerem os defaults da tool.
    return tool.invoke({k: v for k, v in argumentos.items() if v is not None})


@mcp.tool(
    name="total_balance",
    title="Saldo total",
    description="Retorna o saldo total (INCOME - EXPENSES) em todo o histórico.",
    annotations=LEITURA,
)
def total_balance() -> dict[str, Any]:
    return _chamar(_total_balance)


@mcp.tool(
    name="query_transactions",
    title="Consultar transações",
    description="Lista transações por texto, tipo e intervalo de datas.",
    annotations=LEITURA,
)
def query_transactions(
    text_filter: Annotated[Optional[str], Field(description="Filtro em source_text/description.")] = None,
    type_name: Annotated[Optional[str], Field(description="INCOME | EXPENSES | TRANSFER.")] = None,
    date_from_local: Annotated[Optional[str], Field(description="Data inicial local (YYYY-MM-DD).")] = None,
    date_to_local: Annotated[Optional[str], Field(description="Data final local (YYYY-MM-DD).")] = None,
) -> dict[str, Any]:
    return _chamar(
        _query_transactions,
        text_filter=text_filter,
        type_name=type_name,
        date_from_local=date_from_local,
        date_to_local=date_to_local,
    )


@mcp.tool(
    name="daily_balance",
    title="Saldo diário",
    description="Retorna o saldo líquido do dia informado.",
    annotations=LEITURA,
)
def daily_balance(
    date_local: Annotated[str, Field(description="Data no formato YYYY-MM-DD")],
) -> dict[str, Any]:
    return _chamar(_daily_balance, date_local=date_local)


@mcp.tool(
    name="add_transaction",
    title="Registrar transação",
    description="Insere uma transação financeira no banco de dados Postgres.",
    annotations=ESCRITA,
)
def add_transaction(
    amount: Annotated[float, Field(description="Valor da transação, sempre positivo.")],
    source_text: Annotated[str, Field(description="Texto original do usuário.")],
    occurred_at: Annotated[Optional[str], Field(description="Timestamp ISO 8601 ou data YYYY-MM-DD.")] = None,
    type_name: Annotated[Optional[str], Field(description="INCOME | EXPENSES | TRANSFER.")] = None,
    category_name: Annotated[Optional[str], Field(description="Nome da categoria.")] = None,
    description: Annotated[Optional[str], Field(description="Descrição da transação.")] = None,
    payment_method: Annotated[Optional[str], Field(description="Forma de pagamento.")] = None,
) -> dict[str, Any]:
    return _chamar(
        _add_transaction,
        amount=amount,
        source_text=source_text,
        occurred_at=occurred_at,
        type_name=type_name,
        category_name=category_name,
        description=description,
        payment_method=payment_method,
    )


@mcp.tool(
    name="update_transaction",
    title="Atualizar transação",
    description="Atualiza uma transação existente por id, ou por match_text + date_local.",
    annotations=ESCRITA,
)
def update_transaction(
    id: Annotated[Optional[int], Field(description="ID da transação.")] = None,
    match_text: Annotated[Optional[str], Field(description="Texto para localizar a transação sem id.")] = None,
    date_local: Annotated[Optional[str], Field(description="Data local (YYYY-MM-DD), junto com match_text.")] = None,
    amount: Annotated[Optional[float], Field(description="Novo valor.")] = None,
    type_name: Annotated[Optional[str], Field(description="Novo tipo: INCOME | EXPENSES | TRANSFER.")] = None,
    category_name: Annotated[Optional[str], Field(description="Nova categoria (nome).")] = None,
    description: Annotated[Optional[str], Field(description="Nova descrição.")] = None,
    payment_method: Annotated[Optional[str], Field(description="Novo meio de pagamento.")] = None,
    occurred_at: Annotated[Optional[str], Field(description="Novo timestamp ISO 8601.")] = None,
) -> dict[str, Any]:
    return _chamar(
        _update_transaction,
        id=id,
        match_text=match_text,
        date_local=date_local,
        amount=amount,
        type_name=type_name,
        category_name=category_name,
        description=description,
        payment_method=payment_method,
        occurred_at=occurred_at,
    )


if __name__ == "__main__":
    mcp.run()
