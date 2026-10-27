from app.config import DATABASE_URL
import psycopg2

def get_conn():
    if not DATABASE_URL:
        raise ValueError("A variável DATABASE_URL não foi encontrada no .env")
    return psycopg2.connect(DATABASE_URL)
