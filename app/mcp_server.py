from typing import Any, Optional, Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP
import sys
from pathlib import Path
from typing import Annotated, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from app.tools.financeiro import (
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
 



from app.tools.financeiro import (
    add_transaction as _add_transaction,
    query_transactions as _query_transactions,
    total_balance as _total_balance,
    daily_balance as _daily_balance,
    update_transaction as _update_transaction,
)


mcp = FastMCP("financeiro")


LEITURA = {
    "readOnlyHint": True,
}

ESCRITA = {
    "readOnlyHint": False,
}


@mcp.tool(
    name="total_balance",
    title="Saldo total",
    description="Retorna o saldo total acumulado das transações.",
    annotations=LEITURA,
)
def total_balance() -> dict[str, Any]:
    return {
        "balance": _total_balance()
    }


@mcp.tool(
    name="query_transactions",
    title="Consultar transações",
    description="Lista todas as transações cadastradas.",
    annotations=LEITURA,
)
def query_transactions() -> dict[str, Any]:
    transactions = _query_transactions()

    return {
        "transactions": transactions
    }


@mcp.tool(
    name="daily_balance",
    title="Saldo diário",
    description="Retorna o saldo de uma data específica.",
    annotations=LEITURA,
)
def daily_balance(
    date: Annotated[
        str,
        Field(description="Data no formato YYYY-MM-DD")
    ]
) -> dict[str, Any]:

    return {
        "date": date,
        "balance": _daily_balance(date)
    }


@mcp.tool(
    name="add_transaction",
    title="Registrar transação",
    description="Adiciona uma nova transação financeira.",
    annotations=ESCRITA,
)
def add_transaction(
    value: Annotated[
        float,
        Field(description="Valor da transação.")
    ],
    category: Annotated[
        str,
        Field(description="Categoria da transação.")
    ],
    payment_method: Annotated[
        str,
        Field(description="Método de pagamento.")
    ],
) -> dict[str, Any]:

    _add_transaction(
        value,
        category,
        payment_method
    )

    return {
        "status": "success",
        "message": "Transação registrada."
    }


@mcp.tool(
    name="update_transaction",
    title="Atualizar transação",
    description="Atualiza uma transação existente pelo ID.",
    annotations=ESCRITA,
)
def update_transaction(
    transaction_id: Annotated[
        int,
        Field(description="ID da transação.")
    ],
    value: Annotated[
        float,
        Field(description="Novo valor.")
    ],
    category: Annotated[
        str,
        Field(description="Nova categoria.")
    ],
    payment_method: Annotated[
        str,
        Field(description="Novo método de pagamento.")
    ],
) -> dict[str, Any]:

    _update_transaction(
        transaction_id,
        value,
        category,
        payment_method
    )

    return {
        "status": "success",
        "message": "Transação atualizada."
    }


if __name__ == "__main__":
    mcp.run()