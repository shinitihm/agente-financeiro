import os
import re
import unicodedata
from typing import Optional,List

import psycopg2
from dotenv import load_dotenv
from langchain.tools import tool
from pydantic import BaseModel, Field

load_dotenv()

DATABASE_URL = os.getenv("LINK_URL")

def get_conn():
    if not DATABASE_URL:
        raise ValueError("A variável LINK_URL não foi encontrada no .env")
    return psycopg2.connect(DATABASE_URL)


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text


def _normalize_occurred_at(occurred_at: Optional[str]) -> Optional[str]:
    """
    Corrige datas vindas do modelo para evitar bug de timezone.

    Casos tratados:
    - YYYY-MM-DD -> vira meio-dia -03:00
    - YYYY-MM-DDT00:00:00Z -> vira meio-dia -03:00
    - YYYY-MM-DDT00:00:00+00:00 -> vira meio-dia -03:00
    - YYYY-MM-DD 00:00:00+00 -> vira meio-dia -03:00
    """
    if not occurred_at:
        return None

    occurred_at = occurred_at.strip()

    # Caso 1: só data
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", occurred_at):
        return f"{occurred_at}T12:00:00-03:00"

    # Extrai a data base, se existir
    match_date = re.match(r"^(\d{4}-\d{2}-\d{2})", occurred_at)
    if not match_date:
        return occurred_at

    date_part = match_date.group(1)

    # Casos de meia-noite UTC
    midnight_utc_patterns = [
        r"^\d{4}-\d{2}-\d{2}T00:00:00Z$",
        r"^\d{4}-\d{2}-\d{2}T00:00:00\+00:00$",
        r"^\d{4}-\d{2}-\d{2} 00:00:00\+00$",
        r"^\d{4}-\d{2}-\d{2} 00:00:00\+00:00$",
        r"^\d{4}-\d{2}-\d{2}T00:00:00$",
        r"^\d{4}-\d{2}-\d{2} 00:00:00$",
    ]

    for pattern in midnight_utc_patterns:
        if re.fullmatch(pattern, occurred_at):
            return f"{date_part}T12:00:00-03:00"

    return occurred_at


def _safe_close(cur=None, conn=None):
    try:
        if cur:
            cur.close()
    except Exception:
        pass

    try:
        if conn:
            conn.close()
    except Exception:
        pass


# Data de negócio:
# - se o registro estiver salvo exatamente em 00:00:00 UTC, tratamos a data UTC como a data "intencional"
# - caso contrário, usamos a data local de São Paulo
BUSINESS_DATE_SQL = """
(
    CASE
        WHEN (t.occurred_at AT TIME ZONE 'UTC')::time = TIME '00:00:00'
        THEN (t.occurred_at AT TIME ZONE 'UTC')::date
        ELSE (t.occurred_at AT TIME ZONE 'America/Sao_Paulo')::date
    END
)
"""


class AddTransactionArgs(BaseModel):
    amount: float = Field(..., description="Valor da transação, sempre positivo.")
    source_text: str = Field(..., description="Texto original do usuário.")
    occurred_at: Optional[str] = Field(
        default=None,
        description="Timestamp ISO 8601 ou data YYYY-MM-DD."
    )
    category_name: Optional[str] = Field(
        default=None,
        description="Nome da categoria, por exemplo: alimentação, transporte, lazer."
    )
    type_id: Optional[int] = Field(
        default=None,
        description="ID em transaction_types (1=INCOME, 2=EXPENSES, 3=TRANSFER)."
    )
    type_name: Optional[str] = Field(
        default=None,
        description="Nome do tipo: INCOME | EXPENSES | TRANSFER."
    )
    category_id: Optional[int] = Field(
        default=None,
        description="FK da tabela categories."
    )
    description: Optional[str] = Field(default=None, description="Descrição da transação.")
    payment_method: Optional[str] = Field(default=None, description="Forma de pagamento.")


class QueryTransactionsArgs(BaseModel):
    text_filter: Optional[str] = Field(
        default=None,
        description="Filtro de texto para source_text ou description."
    )
    type_name: Optional[str] = Field(
        default=None,
        description="Nome do tipo: INCOME | EXPENSES | TRANSFER."
    )
    date_from_local: Optional[str] = Field(
        default=None,
        description="Data inicial local (YYYY-MM-DD)."
    )
    date_to_local: Optional[str] = Field(
        default=None,
        description="Data final local (YYYY-MM-DD)."
    )


class SumTransactionsArgs(BaseModel):
    type_name: Optional[str] = Field(
        default="EXPENSES",
        description="Tipo a somar: INCOME | EXPENSES | TRANSFER."
    )
    date_from_local: Optional[str] = Field(
        default=None,
        description="Data inicial local inclusiva (YYYY-MM-DD)."
    )
    date_to_local: Optional[str] = Field(
        default=None,
        description="Data final local inclusiva (YYYY-MM-DD)."
    )
    before_date_local: Optional[str] = Field(
        default=None,
        description="Somar transações anteriores a esta data local (YYYY-MM-DD), exclusivo."
    )
    text_filter: Optional[str] = Field(
        default=None,
        description="Filtro opcional por texto em source_text/description."
    )


def _resolve_type_id(cur, type_id: Optional[int], type_name: Optional[str]) -> Optional[int]:
    type_aliases = {
        "INCOME": "INCOME",
        "ENTRADA": "INCOME",
        "RECEITA": "INCOME",
        "SALARIO": "INCOME",
        "SALÁRIO": "INCOME",

        "EXPENSE": "EXPENSES",
        "EXPENSES": "EXPENSES",
        "DESPESA": "EXPENSES",
        "DESPESAS": "EXPENSES",
        "GASTO": "EXPENSES",
        "GASTOS": "EXPENSES",

        "TRANSFER": "TRANSFER",
        "TRANSFERENCIA": "TRANSFER",
        "TRANSFERÊNCIA": "TRANSFER",
    }

    if type_name:
        t = _normalize_text(type_name).upper()
        t = type_aliases.get(t, t)

        cur.execute(
            "SELECT id FROM transaction_types WHERE UPPER(type) = %s LIMIT 1;",
            (t,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    if type_id:
        return int(type_id)

    return 2

def _local_date_filter_sql(field: str = "occurred_at") -> str:
    """
    Retorna um trecho SQL para filtragem por dia local em America/Sao_Paulo.
    Ex.: (occurred_at AT TIME ZONE 'America/Sao_Paulo')::date = %s::date
    """
    return f"(({field} AT TIME ZONE 'America/Sao_Paulo')::date = %s::date)"

def _resolve_category_id(cur, category_id: Optional[int], category_name: Optional[str]) -> Optional[int]:
    if category_id:
        return int(category_id)

    if not category_name:
        return None

    raw = _normalize_text(category_name)

    category_aliases = {
        "chocolate": "alimentacao",
        "carne": "alimentacao",
        "lanche": "alimentacao",
        "comida": "alimentacao",
        "mcdonalds": "alimentacao",
        "mcdonald": "alimentacao",
        "mercado": "alimentacao",
        "restaurante": "alimentacao",
        "ifood": "alimentacao",

        "uber": "transporte",
        "onibus": "transporte",
        "ônibus": "transporte",
        "gasolina": "transporte",
        "combustivel": "transporte",
        "combustível": "transporte",

        "cinema": "lazer",
        "jogo": "lazer",
        "netflix": "lazer",

        "salario": "salario",
        "salário": "salario",
        "pagamento": "salario",

        "pix": "transferencia",
        "transferencia": "transferencia",
        "transferência": "transferencia",
    }

    normalized = category_aliases.get(raw, raw)

    cur.execute(
        "SELECT id FROM categories WHERE LOWER(name) = %s LIMIT 1;",
        (normalized,)
    )
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute(
        "SELECT id FROM categories WHERE LOWER(name) LIKE %s LIMIT 1;",
        (f"%{normalized}%",)
    )
    row = cur.fetchone()
    if row:
        return row[0]

    return None


@tool("add_transaction", args_schema=AddTransactionArgs)
def add_transaction(
    amount: float,
    source_text: str,
    category_id: Optional[int] = None,
    category_name: Optional[str] = None,
    occurred_at: Optional[str] = None,
    type_id: Optional[int] = None,
    type_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
) -> dict:
    """Insere uma transação financeira no banco de dados Postgres."""
    conn = None
    cur = None

    try:
        conn = get_conn()
        cur = conn.cursor()

        resolved_type_id = _resolve_type_id(cur, type_id, type_name)
        resolved_category_id = _resolve_category_id(cur, category_id, category_name)
        occurred_at = _normalize_occurred_at(occurred_at)

        if not resolved_type_id:
            return {
                "status": "error",
                "message": "Tipo inválido. Use INCOME, EXPENSES ou TRANSFER."
            }

        if occurred_at:
            cur.execute(
                """
                INSERT INTO transactions
                    (amount, type, category_id, description, payment_method, occurred_at, source_text)
                VALUES
                    (%s, %s, %s, %s, %s, %s::timestamptz, %s)
                RETURNING id, category_id, occurred_at;
                """,
                (
                    amount,
                    resolved_type_id,
                    resolved_category_id,
                    description,
                    payment_method,
                    occurred_at,
                    source_text,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO transactions
                    (amount, type, category_id, description, payment_method, occurred_at, source_text)
                VALUES
                    (%s, %s, %s, %s, %s, NOW(), %s)
                RETURNING id, category_id, occurred_at;
                """,
                (
                    amount,
                    resolved_type_id,
                    resolved_category_id,
                    description,
                    payment_method,
                    source_text,
                ),
            )

        new_id, saved_category_id, occurred = cur.fetchone()
        conn.commit()

        return {
            "status": "ok",
            "id": new_id,
            "category_id": saved_category_id,
            "occurred_at": str(occurred),
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"status": "error", "message": str(e)}

    finally:
        _safe_close(cur, conn)


@tool("query_transactions", args_schema=QueryTransactionsArgs)
def query_transactions(
    text_filter: Optional[str] = None,
    type_name: Optional[str] = None,
    date_from_local: Optional[str] = None,
    date_to_local: Optional[str] = None,
) -> dict:
    """
    Lista transações por texto, tipo e intervalo de datas.
    """
    conn = None
    cur = None

    try:
        conn = get_conn()
        cur = conn.cursor()

        sql = f"""
            SELECT
                t.id,
                t.amount,
                tt.type,
                t.category_id,
                c.name AS category_name,
                t.description,
                t.payment_method,
                t.occurred_at,
                t.source_text,
                {BUSINESS_DATE_SQL} AS business_date
            FROM transactions t
            LEFT JOIN transaction_types tt
                ON tt.id = t.type
            LEFT JOIN categories c
                ON c.id = t.category_id
            WHERE 1=1
        """
        params = []

        if text_filter:
            like_value = f"%{text_filter.lower()}%"
            sql += """
                AND (
                    LOWER(COALESCE(t.source_text, '')) LIKE %s
                    OR LOWER(COALESCE(t.description, '')) LIKE %s
                )
            """
            params.extend([like_value, like_value])

        if type_name:
            resolved_type_id = _resolve_type_id(cur, None, type_name)
            if resolved_type_id:
                sql += " AND t.type = %s"
                params.append(resolved_type_id)

        if date_from_local:
            sql += f" AND {BUSINESS_DATE_SQL} >= %s::date"
            params.append(date_from_local)

        if date_to_local:
            sql += f" AND {BUSINESS_DATE_SQL} <= %s::date"
            params.append(date_to_local)

        if date_from_local or date_to_local:
            sql += " ORDER BY business_date ASC, t.occurred_at ASC"
        else:
            sql += " ORDER BY t.occurred_at DESC"

        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

        items = []
        total_amount = 0.0

        for row in rows:
            amount = float(row[1])
            total_amount += amount

            items.append({
                "id": row[0],
                "amount": amount,
                "type": row[2],
                "category_id": row[3],
                "category_name": row[4],
                "description": row[5],
                "payment_method": row[6],
                "occurred_at": str(row[7]),
                "source_text": row[8],
                "business_date": str(row[9]),
            })

        return {
            "status": "ok",
            "count": len(items),
            "total_amount": total_amount,
            "items": items,
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"status": "error", "message": str(e)}

    finally:
        _safe_close(cur, conn)


@tool("sum_transactions", args_schema=SumTransactionsArgs)
def sum_transactions(
    type_name: Optional[str] = "EXPENSES",
    date_from_local: Optional[str] = None,
    date_to_local: Optional[str] = None,
    before_date_local: Optional[str] = None,
    text_filter: Optional[str] = None,
) -> dict:
    """
    Soma transações por período.
    """
    conn = None
    cur = None

    try:
        conn = get_conn()
        cur = conn.cursor()

        sql = f"""
            SELECT
                COUNT(*) AS total_registros,
                COALESCE(SUM(t.amount), 0) AS total_valor
            FROM transactions t
            WHERE 1=1
        """
        params = []

        if type_name:
            resolved_type_id = _resolve_type_id(cur, None, type_name)
            if resolved_type_id:
                sql += " AND t.type = %s"
                params.append(resolved_type_id)

        if text_filter:
            like_value = f"%{text_filter.lower()}%"
            sql += """
                AND (
                    LOWER(COALESCE(t.source_text, '')) LIKE %s
                    OR LOWER(COALESCE(t.description, '')) LIKE %s
                )
            """
            params.extend([like_value, like_value])

        if date_from_local:
            sql += f" AND {BUSINESS_DATE_SQL} >= %s::date"
            params.append(date_from_local)

        if date_to_local:
            sql += f" AND {BUSINESS_DATE_SQL} <= %s::date"
            params.append(date_to_local)

        if before_date_local:
            sql += f" AND {BUSINESS_DATE_SQL} < %s::date"
            params.append(before_date_local)

        cur.execute(sql, tuple(params))
        row = cur.fetchone()

        count = int(row[0]) if row and row[0] is not None else 0
        total_value = float(row[1]) if row and row[1] is not None else 0.0

        return {
            "status": "ok",
            "count": count,
            "total_amount": total_value,
            "type_name": type_name,
            "date_from_local": date_from_local,
            "date_to_local": date_to_local,
            "before_date_local": before_date_local,
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"status": "error", "message": str(e)}

    finally:
        _safe_close(cur, conn)


@tool("total_balance")
def total_balance() -> dict:
    """
    Retorna o saldo total (INCOME - EXPENSES) em todo o histórico.
    Ignora TRANSFER.
    """
    conn = None
    cur = None

    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT COALESCE(SUM(
                CASE
                    WHEN type = 1 THEN amount
                    WHEN type = 2 THEN -amount
                    ELSE 0
                END
            ), 0) AS saldo_total
            FROM transactions;
        """)

        row = cur.fetchone()
        return {
            "status": "ok",
            "total_balance": float(row[0]) if row and row[0] is not None else 0.0
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"status": "error", "message": str(e)}

    finally:
        _safe_close(cur, conn)


@tool("daily_balance")
def daily_balance(date_local: str) -> dict:
    """
    Retorna o saldo líquido do dia informado.
    """
    conn = None
    cur = None

    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute(f"""
            SELECT COALESCE(SUM(
                CASE
                    WHEN type = 1 THEN amount
                    WHEN type = 2 THEN -amount
                    ELSE 0
                END
            ), 0) AS saldo_dia
            FROM transactions t
            WHERE {BUSINESS_DATE_SQL} = %s::date;
        """, (date_local,))

        row = cur.fetchone()
        return {
            "status": "ok",
            "daily_balance": float(row[0]) if row and row[0] is not None else 0.0
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"status": "error", "message": str(e)}

    finally:
        _safe_close(cur, conn)

class UpdateTransactionArgs(BaseModel):
    id: Optional[int] = Field(
        default=None,
        description="ID da transação a atualizar. Se ausente, será feita uma busca por (match_text + date_local)."
    )
    match_text: Optional[str] = Field(
        default=None,
        description="Texto para localizar transação quando id não for informado (busca em source_text/description)."
    )
    date_local: Optional[str] = Field(
        default=None,
        description="Data local (YYYY-MM-DD) em America/Sao_Paulo; usado em conjunto com match_text quando id ausente."
    )
    amount: Optional[float] = Field(default=None, description="Novo valor.")
    type_id: Optional[int] = Field(default=None, description="Novo type_id (1/2/3).")
    type_name: Optional[str] = Field(default=None, description="Novo type_name: INCOME | EXPENSES | TRANSFER.")
    category_id: Optional[int] = Field(default=None, description="Nova categoria (id).")
    category_name: Optional[str] = Field(default=None, description="Nova categoria (nome).")
    description: Optional[str] = Field(default=None, description="Nova descrição.")
    payment_method: Optional[str] = Field(default=None, description="Novo meio de pagamento.")
    occurred_at: Optional[str] = Field(default=None, description="Novo timestamp ISO 8601.")

@tool("update_transaction", args_schema=UpdateTransactionArgs)
def update_transaction(
    id: Optional[int] = None,
    match_text: Optional[str] = None,
    date_local: Optional[str] = None,
    amount: Optional[float] = None,
    type_id: Optional[int] = None,
    type_name: Optional[str] = None,
    category_id: Optional[int] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
    occurred_at: Optional[str] = None,
) -> dict:
    """
    Atualiza uma transação existente.
    Estratégias:
      - Se 'id' for informado: atualiza diretamente por ID.
      - Caso contrário: localiza a transação mais recente que combine (match_text em source_text/description)
        E (date_local em America/Sao_Paulo), então atualiza.
    Retorna: status, rows_affected, id, e o registro atualizado.
    """
    if not any([amount, type_id, type_name, category_id, category_name, description, payment_method, occurred_at]):
        return {"status": "error", "message": "Nada para atualizar: forneça pelo menos um campo (amount, type, category, description, payment_method, occurred_at)."}

    conn = get_conn()
    cur = conn.cursor()
    try:
        # Resolve target_id
        target_id = id
        if target_id is None:
            if not match_text or not date_local:
                return {"status": "error", "message": "Sem 'id': informe match_text E date_local para localizar o registro."}

            # Buscar o mais recente no dia local informado que combine o texto
            cur.execute(
                f"""
                SELECT t.id
                FROM transactions t
                WHERE (t.source_text ILIKE %s OR t.description ILIKE %s)
                  AND {_local_date_filter_sql("t.occurred_at")}
                ORDER BY t.occurred_at DESC
                LIMIT 1;
                """,
                (f"%{match_text}%", f"%{match_text}%", date_local)
            )
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": "Nenhuma transação encontrada para os filtros fornecidos."}
            target_id = row[0]

        # Resolver type_id / category_id a partir de nomes, se fornecidos
        resolved_type_id = _resolve_type_id(cur, type_id, type_name) if (type_id or type_name) else None
        resolved_category_id = category_id
        if category_name and not category_id:
            resolved_category_id = resolved_category_id(cur, category_name)

        # Montar SET dinâmico
        sets = []
        params: List[object] = []
        if amount is not None:
            sets.append("amount = %s")
            params.append(amount)
        if resolved_type_id is not None:
            sets.append("type = %s")
            params.append(resolved_type_id)
        if resolved_category_id is not None:
            sets.append("category_id = %s")
            params.append(resolved_category_id)
        if description is not None:
            sets.append("description = %s")
            params.append(description)
        if payment_method is not None:
            sets.append("payment_method = %s")
            params.append(payment_method)
        if occurred_at is not None:
            sets.append("occurred_at = %s::timestamptz")
            params.append(occurred_at)

        if not sets:
            return {"status": "error", "message": "Nenhum campo válido para atualizar."}

        params.append(target_id)

        cur.execute(
            f"UPDATE transactions SET {', '.join(sets)} WHERE id = %s;",
            params
        )
        rows_affected = cur.rowcount
        conn.commit()

        # Retornar o registro atualizado
        cur.execute(
            """
            SELECT
              t.id, t.occurred_at, t.amount, tt.type AS type_name,
              c.name AS category_name, t.description, t.payment_method, t.source_text
            FROM transactions t
            JOIN transaction_types tt ON tt.id = t.type
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.id = %s;
            """,
            (target_id,)
        )
        r = cur.fetchone()
        updated = None
        if r:
            updated = {
                "id": r[0],
                "occurred_at": str(r[1]),
                "amount": float(r[2]),
                "type": r[3],
                "category": r[4],
                "description": r[5],
                "payment_method": r[6],
                "source_text": r[7],
            }

        return {
            "status": "ok",
            "rows_affected": rows_affected,
            "id": target_id,
            "updated": updated
        }

    except Exception as e:
        conn.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

TOOLS = [add_transaction, query_transactions, sum_transactions, total_balance, daily_balance]