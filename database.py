import psycopg2
from psycopg2.extras import RealDictCursor
import os

def get_db_connection():
    url = os.environ.get('DATABASE_URL')
    conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Create users table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    
    # 2. Create expenses table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            date DATE NOT NULL,
            category TEXT NOT NULL,
            amount DECIMAL(12, 2) NOT NULL,
            description TEXT
        )
    ''')
    
    # 3. Create category_budgets table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS category_budgets (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            category TEXT NOT NULL,
            month TEXT NOT NULL,
            year TEXT NOT NULL,
            budget_limit DECIMAL(12, 2) NOT NULL,
            UNIQUE(user_id, category, month, year)
        )
    ''')

    conn.commit()
    cur.close()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialization complete.")