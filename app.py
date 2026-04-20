from flask import Flask, render_template, request, redirect, url_for, flash
from database import get_db_connection, init_db
from datetime import date
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

def get_all_categories(conn, user_id):
    base_cats = ['Food', 'Transport', 'Shopping', 'Bills', 'Health', 'Entertainment', 'Other']
    cur = conn.cursor()
    cur.execute('SELECT DISTINCT category FROM expenses WHERE user_id = %s', (user_id,))
    rows = cur.fetchall()
    cur.execute('SELECT DISTINCT category FROM category_budgets WHERE user_id = %s', (user_id,))
    budget_rows = cur.fetchall()
    cur.close()
    
    custom_cats = set(r['category'] for r in rows)
    custom_cats.update(r['category'] for r in budget_rows)
    
    for cat in base_cats:
        if cat in custom_cats:
            custom_cats.remove(cat)
            
    return base_cats[:-1] + sorted(list(custom_cats)) + ['Other']

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'expense_tracker_secret')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    if user_id is None:
        return None
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE id = %s', (int(user_id),))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if user:
        return User(id=user['id'], username=user['username'])
    return None

# Database Initialization & Default Admin
init_db()
conn = get_db_connection()
cur = conn.cursor()
cur.execute('SELECT * FROM users WHERE id = 1')
admin = cur.fetchone()
if not admin:
    # First boot after migration: assign password 'admin'
    cur.execute('INSERT INTO users (id, username, password_hash) VALUES (%s, %s, %s)',
                 (1, 'admin', generate_password_hash('admin')))
    conn.commit()
cur.close()
conn.close()

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        if not username or not password:
            flash('Username and password are required.', 'error')
            return redirect(url_for('register'))
            
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cur.fetchone()
        
        if user:
            cur.close()
            conn.close()
            flash('Username already exists. Please choose a different one.', 'error')
            return redirect(url_for('register'))
            
        cur.execute('INSERT INTO users (username, password_hash) VALUES (%s, %s)',
                     (username, generate_password_hash(password)))
        conn.commit()
        cur.close()
        conn.close()
        
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            user_obj = User(id=user['id'], username=user['username'])
            login_user(user_obj, remember=True)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'error')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    
    cur.execute('SELECT COUNT(*) as count FROM expenses WHERE user_id = %s', (current_user.id,))
    total_count = cur.fetchone()['count']
    total_pages = (total_count + per_page - 1) // per_page
    
    cur.execute(
        'SELECT * FROM expenses WHERE user_id = %s ORDER BY date DESC LIMIT %s OFFSET %s',
        (current_user.id, per_page, offset)
    )
    expenses = cur.fetchall()
    
    today = date.today()
    cur.execute(
        '''SELECT SUM(amount) as total FROM expenses 
           WHERE user_id = %s AND TO_CHAR(date::DATE, 'MM') = %s AND TO_CHAR(date::DATE, 'YYYY') = %s''',
        (current_user.id, str(today.month).zfill(2), str(today.year))
    )
    month_total = cur.fetchone()
    
    current_month_total = month_total['total'] if month_total['total'] else 0
    
    cur.execute(
        '''SELECT SUM(budget_limit) as total_budget FROM category_budgets
           WHERE user_id = %s AND month = %s AND year = %s''',
        (current_user.id, str(today.month).zfill(2), str(today.year))
    )
    budget_total_row = cur.fetchone()
    
    total_budget = budget_total_row['total_budget'] if budget_total_row['total_budget'] else 0
    
    spent_status = 'low'
    if total_budget > 0:
        ratio = float(current_month_total) / float(total_budget)
        if ratio > 1.0:
            spent_status = 'extra-high'
        elif ratio > 0.8:
            spent_status = 'high'
        elif ratio > 0.5:
            spent_status = 'medium'
    else:
        # Fallback if no budgets are set
        if float(current_month_total) > 50000:
            spent_status = 'extra-high'
        elif float(current_month_total) > 20000:
            spent_status = 'high'
        elif float(current_month_total) > 5000:
            spent_status = 'medium'
            
    cur.close()
    conn.close()
    
    return render_template('index.html', 
                           expenses=expenses, 
                           today=today, 
                           current_month_total=current_month_total,
                           page=page,
                           total_pages=total_pages,
                           spent_status=spent_status)

@app.route('/add', methods=['POST'])
@login_required
def add():
    date_val = request.form.get('date')
    category = request.form.get('category')
    custom_category = request.form.get('custom_category', '').strip()
    amount = request.form.get('amount')
    description = request.form.get('description', '')

    if category == 'Other' and custom_category:
        category = custom_category

    if not amount or float(amount) <= 0:
        flash('Amount must be a positive number!', 'error')
        return redirect(url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO expenses (user_id, date, category, amount, description) VALUES (%s, %s, %s, %s, %s)',
        (current_user.id, date_val, category, float(amount), description)
    )
    conn.commit()
    cur.close()
    conn.close()
    flash('Expense added successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/delete/<int:id>', methods=['GET', 'POST'])
def delete(id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM expenses WHERE id = %s', (id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Expense deleted!', 'success')
    return redirect(url_for('index'))

@app.route('/clear', methods=['GET', 'POST'])
def clear():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM expenses')
    conn.commit()
    cur.close()
    conn.close()
    flash('All data cleared successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/summary')
@login_required
def summary():
    conn = get_db_connection()
    cur = conn.cursor()
    today = date.today()
    month = request.args.get('month', today.month, type=int)
    year = request.args.get('year', today.year, type=int)

    cur.execute(
        '''SELECT category, SUM(amount) as total
           FROM expenses
           WHERE user_id = %s AND TO_CHAR(date::DATE, 'MM') = %s AND TO_CHAR(date::DATE, 'YYYY') = %s
           GROUP BY category''',
        (current_user.id, str(month).zfill(2), str(year))
    )
    expenses = cur.fetchall()

    cur.execute(
        '''SELECT SUM(amount) as total FROM expenses
           WHERE user_id = %s AND TO_CHAR(date::DATE, 'MM') = %s AND TO_CHAR(date::DATE, 'YYYY') = %s''',
        (current_user.id, str(month).zfill(2), str(year))
    )
    total = cur.fetchone()

    cur.execute('''
        SELECT category, budget_limit FROM category_budgets
        WHERE user_id = %s AND month = %s AND year = %s
    ''', (current_user.id, str(month).zfill(2), str(year)))
    budgets_data = cur.fetchall()
    
    budget_dict = {row['category']: row['budget_limit'] for row in budgets_data}
    spent_dict = {row['category']: row['total'] for row in expenses}

    category_data = []
    total_budget = 0
    total_spent = total['total'] or 0
    all_cats = get_all_categories(conn, current_user.id)

    for category in all_cats:
        budget = budget_dict.get(category)
        spent = spent_dict.get(category, 0)
        
        if budget is not None:
            total_budget += float(budget)
            percent = (float(spent) / float(budget) * 100) if float(budget) > 0 else (100 if float(spent) > 0 else 0)
            if percent < 80:
                status = 'green'
            elif percent < 100:
                status = 'orange'
            else:
                status = 'red'
        else:
            percent = 0
            status = 'neutral'
            
        if budget is not None or float(spent) > 0:
            category_data.append({
                'category': category,
                'spent': spent,
                'budget': budget,
                'percent': percent,
                'status': status
            })

    remaining = float(total_budget) - float(total_spent)

    cur.close()
    conn.close()
    return render_template('summary.html',
                           category_data=category_data,
                           total=total_spent,
                           month=month,
                           year=year,
                           total_budget=total_budget,
                           remaining=remaining)

@app.route('/budgets', methods=['GET', 'POST'])
@login_required
def budgets():
    conn = get_db_connection()
    cur = conn.cursor()
    today = date.today()
    
    all_cats = get_all_categories(conn, current_user.id)
    
    if request.method == 'POST':
        month = request.form.get('month', type=int)
        year = request.form.get('year', type=int)
        
        for category in all_cats:
            budget_limit = request.form.get(f'budget_{category}', type=float)
            if budget_limit is not None and budget_limit >= 0:
                cur.execute('''
                    INSERT INTO category_budgets (user_id, category, month, year, budget_limit)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT(user_id, category, month, year) DO UPDATE SET budget_limit=EXCLUDED.budget_limit
                ''', (current_user.id, category, str(month).zfill(2), str(year), budget_limit))
            elif budget_limit is None or budget_limit == "":
                cur.execute('''
                    DELETE FROM category_budgets WHERE user_id = %s AND category = %s AND month = %s AND year = %s
                ''', (current_user.id, category, str(month).zfill(2), str(year)))
                
        conn.commit()
        flash('Budgets saved successfully!', 'success')
        return redirect(url_for('budgets', month=month, year=year))

    month = request.args.get('month', today.month, type=int)
    year = request.args.get('year', today.year, type=int)

    cur.execute('''
        SELECT category, budget_limit FROM category_budgets
        WHERE user_id = %s AND month = %s AND year = %s
    ''', (current_user.id, str(month).zfill(2), str(year)))
    budgets_data = cur.fetchall()
    
    budget_dict = {row['category']: row['budget_limit'] for row in budgets_data}
    
    cur.close()
    conn.close()
    return render_template('budgets.html', month=month, year=year, budget_dict=budget_dict, categories=all_cats)

@app.route('/edit/<int:id>')
@login_required
def edit(id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'SELECT * FROM expenses WHERE id = %s AND user_id = %s', (id, current_user.id)
    )
    expense = cur.fetchone()
    if expense is None:
        cur.close()
        conn.close()
        flash('Expense not found!', 'error')
        return redirect(url_for('index'))
        
    all_cats = get_all_categories(conn, current_user.id)
    cur.close()
    conn.close()
    return render_template('edit.html', expense=expense, all_categories=all_cats)

@app.route('/update/<int:id>', methods=['POST'])
@login_required
def update(id):
    date_val = request.form.get('date')
    category = request.form.get('category')
    custom_category = request.form.get('custom_category', '').strip()
    amount = request.form.get('amount')
    description = request.form.get('description', '')

    if category == 'Other' and custom_category:
        category = custom_category

    if not amount or float(amount) <= 0:
        flash('Amount must be a positive number!', 'error')
        return redirect(url_for('edit', id=id))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Verify ownership
    cur.execute('SELECT * FROM expenses WHERE id = %s AND user_id = %s', (id, current_user.id))
    expense = cur.fetchone()
    if not expense:
        cur.close()
        conn.close()
        flash('Unauthorized or not found!', 'error')
        return redirect(url_for('index'))
        
    cur.execute(
        '''UPDATE expenses
           SET date=%s, category=%s, amount=%s, description=%s
           WHERE id=%s AND user_id=%s''',
        (date_val, category, float(amount), description, id, current_user.id)
    )
    conn.commit()
    cur.close()
    conn.close()
    flash('Expense updated successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/search')
@login_required
def search():
    conn = get_db_connection()
    cur = conn.cursor()

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    category = request.args.get('category')
    min_amount = request.args.get('min_amount')
    max_amount = request.args.get('max_amount')

    query = "SELECT * FROM expenses WHERE user_id = %s"
    params = [current_user.id]

    if start_date:
        query += " AND date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND date <= %s"
        params.append(end_date)

    if category:
        query += " AND category = %s"
        params.append(category)

    if min_amount:
        query += " AND amount >= %s"
        params.append(float(min_amount))

    if max_amount:
        query += " AND amount <= %s"
        params.append(float(max_amount))

    query += " ORDER BY date DESC"

    cur.execute(query, params)
    expenses = cur.fetchall()
    
    # Get all distinct categories for the dropdown
    all_cats = get_all_categories(conn, current_user.id)
    
    cur.close()
    conn.close()
    return render_template('search.html', 
                           expenses=expenses,
                           start_date=start_date,
                           end_date=end_date,
                           category=category,
                           min_amount=min_amount,
                           max_amount=max_amount,
                           all_categories=all_cats)

if __name__ == '__main__':
    app.run(debug=True)