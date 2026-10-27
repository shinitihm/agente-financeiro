# Conteúdo do arquivo: app/tools/financeiro.py

from app.config import DATABASE_URL
import psycopg2
from connection import get_conn

def add_transaction(value, category, payment_method):
    conn = get_conn()
    with conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO transactions (value, category, payment_method) VALUES (%s, %s, %s)",
                (value, category, payment_method)
            )

def query_transactions():
    conn = get_conn()
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM transactions")
            return cursor.fetchall()

def total_balance():
    conn = get_conn()
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT SUM(value) FROM transactions")
            return cursor.fetchone()[0]

def daily_balance(date):
    conn = get_conn()
    with conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT SUM(value) FROM transactions WHERE DATE(transaction_date) = %s",
                (date,)
            )
            return cursor.fetchone()[0]

def update_transaction(transaction_id, value, category, payment_method):
    conn = get_conn()
    with conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE transactions SET value = %s, category = %s, payment_method = %s WHERE id = %s",
                (value, category, payment_method, transaction_id)
            )

TOOLS = [add_transaction, query_transactions, total_balance, daily_balance, update_transaction]