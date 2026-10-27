from app.config import DATABASE_URL
import psycopg2

def get_conn():
    
    return psycopg2.connect(DATABASE_URL)