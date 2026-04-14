import sqlite3

def get_db_connection():
    conn = sqlite3.connect('expenses.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    
    # 1. Create users table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    
    # Check if we need to migrate an existing database
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='expenses'")
    expenses_exists = cursor.fetchone()
    
    if expenses_exists:
        cursor.execute("PRAGMA table_info(expenses)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'user_id' not in columns:
            print("Running database migration... assigning existing data to admin (user_id=1)")
            
            # Add user_id to expenses
            conn.execute('ALTER TABLE expenses ADD COLUMN user_id INTEGER DEFAULT 1')
            
            # Check if category_budgets exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='category_budgets'")
            budgets_exists = cursor.fetchone()
            
            if budgets_exists:
                # Recreate category_budgets with user_id uniquely scoped
                conn.execute('ALTER TABLE category_budgets RENAME TO category_budgets_old')
                
                conn.execute('''
                    CREATE TABLE category_budgets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL DEFAULT 1,
                        category TEXT NOT NULL,
                        month TEXT NOT NULL,
                        year TEXT NOT NULL,
                        budget_limit REAL NOT NULL,
                        UNIQUE(user_id, category, month, year)
                    )
                ''')
                
                # Copy data over
                conn.execute('''
                    INSERT INTO category_budgets (id, user_id, category, month, year, budget_limit)
                    SELECT id, 1, category, month, year, budget_limit FROM category_budgets_old
                ''')
                
                conn.execute('DROP TABLE category_budgets_old')
    
    # Ensure tables exist for fresh installs
    conn.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS category_budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            month TEXT NOT NULL,
            year TEXT NOT NULL,
            budget_limit REAL NOT NULL,
            UNIQUE(user_id, category, month, year)
        )
    ''')

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database upgrade complete.")