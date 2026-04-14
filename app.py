from flask import Flask, render_template, request, redirect, url_for, flash
from database import get_db_connection, init_db
from datetime import date
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

def get_all_categories(conn, user_id):
    base_cats = ['Food', 'Transport', 'Shopping', 'Bills', 'Health', 'Entertainment', 'Other']
    rows = conn.execute('SELECT DISTINCT category FROM expenses WHERE user_id = ?', (user_id,)).fetchall()
    budget_rows = conn.execute('SELECT DISTINCT category FROM category_budgets WHERE user_id = ?', (user_id,)).fetchall()
    
    custom_cats = set(r['category'] for r in rows)
    custom_cats.update(r['category'] for r in budget_rows)
    
    for cat in base_cats:
        if cat in custom_cats:
            custom_cats.remove(cat)
            
    return base_cats[:-1] + sorted(list(custom_cats)) + ['Other']

app = Flask(__name__)
app.secret_key = 'expense_tracker_secret'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if user:
        return User(id=user['id'], username=user['username'])
    return None

# Generate default admin if not exists
conn = get_db_connection()
import os

if not os.path.exists("expenses.db") or os.path.getsize("expenses.db") == 0:
    init_db()

admin = conn.execute('SELECT * FROM users WHERE id = 1').fetchone()
if not admin:
    # First boot after migration: assign password 'admin'
    conn.execute('INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)',
                 (1, 'admin', generate_password_hash('admin')))
    conn.commit()
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
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if user:
            conn.close()
            flash('Username already exists. Please choose a different one.', 'error')
            return redirect(url_for('register'))
            
        conn.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)',
                     (username, generate_password_hash(password)))
        conn.commit()
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
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
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
    
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    
    total_count = conn.execute('SELECT COUNT(*) FROM expenses WHERE user_id = ?', (current_user.id,)).fetchone()[0]
    total_pages = (total_count + per_page - 1) // per_page
    
    expenses = conn.execute(
        'SELECT * FROM expenses WHERE user_id = ? ORDER BY date DESC LIMIT ? OFFSET ?',
        (current_user.id, per_page, offset)
    ).fetchall()
    
    today = date.today()
    month_total = conn.execute(
        '''SELECT SUM(amount) as total FROM expenses 
           WHERE user_id = ? AND strftime('%m', date) = ? AND strftime('%Y', date) = ?''',
        (current_user.id, str(today.month).zfill(2), str(today.year))
    ).fetchone()
    
    current_month_total = month_total['total'] if month_total['total'] else 0
    
    budget_total_row = conn.execute(
        '''SELECT SUM(budget_limit) as total_budget FROM category_budgets
           WHERE user_id = ? AND month = ? AND year = ?''',
        (current_user.id, str(today.month).zfill(2), str(today.year))
    ).fetchone()
    
    total_budget = budget_total_row['total_budget'] if budget_total_row['total_budget'] else 0
    
    spent_status = 'low'
    if total_budget > 0:
        ratio = current_month_total / total_budget
        if ratio > 1.0:
            spent_status = 'extra-high'
        elif ratio > 0.8:
            spent_status = 'high'
        elif ratio > 0.5:
            spent_status = 'medium'
    else:
        # Fallback if no budgets are set
        if current_month_total > 50000:
            spent_status = 'extra-high'
        elif current_month_total > 20000:
            spent_status = 'high'
        elif current_month_total > 5000:
            spent_status = 'medium'
            
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
    conn.execute(
        'INSERT INTO expenses (user_id, date, category, amount, description) VALUES (?, ?, ?, ?, ?)',
        (current_user.id, date_val, category, float(amount), description)
    )
    conn.commit()
    conn.close()
    flash('Expense added successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/delete/<int:id>', methods=['GET', 'POST'])
def delete(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM expenses WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Expense deleted!', 'success')
    return redirect(url_for('index'))

@app.route('/clear', methods=['GET', 'POST'])
def clear():
    conn = get_db_connection()
    conn.execute('DELETE FROM expenses')
    conn.commit()
    conn.close()
    flash('All data cleared successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/summary')
@login_required
def summary():
    conn = get_db_connection()
    today = date.today()
    month = request.args.get('month', today.month, type=int)
    year = request.args.get('year', today.year, type=int)

    expenses = conn.execute(
        '''SELECT category, SUM(amount) as total
           FROM expenses
           WHERE user_id = ? AND strftime('%m', date) = ? AND strftime('%Y', date) = ?
           GROUP BY category''',
        (current_user.id, str(month).zfill(2), str(year))
    ).fetchall()

    total = conn.execute(
        '''SELECT SUM(amount) as total FROM expenses
           WHERE user_id = ? AND strftime('%m', date) = ? AND strftime('%Y', date) = ?''',
        (current_user.id, str(month).zfill(2), str(year))
    ).fetchone()

    budgets_data = conn.execute('''
        SELECT category, budget_limit FROM category_budgets
        WHERE user_id = ? AND month = ? AND year = ?
    ''', (current_user.id, str(month).zfill(2), str(year))).fetchall()
    
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
            total_budget += budget
            percent = (spent / budget * 100) if budget > 0 else (100 if spent > 0 else 0)
            if percent < 80:
                status = 'green'
            elif percent < 100:
                status = 'orange'
            else:
                status = 'red'
        else:
            percent = 0
            status = 'neutral'
            
        if budget is not None or spent > 0:
            category_data.append({
                'category': category,
                'spent': spent,
                'budget': budget,
                'percent': percent,
                'status': status
            })

    remaining = total_budget - total_spent

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
    today = date.today()
    
    all_cats = get_all_categories(conn, current_user.id)
    
    if request.method == 'POST':
        month = request.form.get('month', type=int)
        year = request.form.get('year', type=int)
        
        for category in all_cats:
            budget_limit = request.form.get(f'budget_{category}', type=float)
            if budget_limit is not None and budget_limit >= 0:
                conn.execute('''
                    INSERT INTO category_budgets (user_id, category, month, year, budget_limit)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, category, month, year) DO UPDATE SET budget_limit=excluded.budget_limit
                ''', (current_user.id, category, str(month).zfill(2), str(year), budget_limit))
            elif budget_limit is None or budget_limit == "":
                conn.execute('''
                    DELETE FROM category_budgets WHERE user_id = ? AND category = ? AND month = ? AND year = ?
                ''', (current_user.id, category, str(month).zfill(2), str(year)))
                
        conn.commit()
        flash('Budgets saved successfully!', 'success')
        return redirect(url_for('budgets', month=month, year=year))

    month = request.args.get('month', today.month, type=int)
    year = request.args.get('year', today.year, type=int)

    budgets_data = conn.execute('''
        SELECT category, budget_limit FROM category_budgets
        WHERE user_id = ? AND month = ? AND year = ?
    ''', (current_user.id, str(month).zfill(2), str(year))).fetchall()
    
    budget_dict = {row['category']: row['budget_limit'] for row in budgets_data}
    
    conn.close()
    return render_template('budgets.html', month=month, year=year, budget_dict=budget_dict, categories=all_cats)

@app.route('/edit/<int:id>')
@login_required
def edit(id):
    conn = get_db_connection()
    expense = conn.execute(
        'SELECT * FROM expenses WHERE id = ? AND user_id = ?', (id, current_user.id)
    ).fetchone()
    if expense is None:
        flash('Expense not found!', 'error')
        return redirect(url_for('index'))
        
    all_cats = get_all_categories(conn, current_user.id)
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
    
    # Verify ownership
    expense = conn.execute('SELECT * FROM expenses WHERE id = ? AND user_id = ?', (id, current_user.id)).fetchone()
    if not expense:
        conn.close()
        flash('Unauthorized or not found!', 'error')
        return redirect(url_for('index'))
        
    conn.execute(
        '''UPDATE expenses
           SET date=?, category=?, amount=?, description=?
           WHERE id=? AND user_id=?''',
        (date_val, category, float(amount), description, id, current_user.id)
    )
    conn.commit()
    conn.close()
    flash('Expense updated successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/search')
@login_required
def search():
    conn = get_db_connection()

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    category = request.args.get('category')
    min_amount = request.args.get('min_amount')
    max_amount = request.args.get('max_amount')

    query = "SELECT * FROM expenses WHERE user_id = ?"
    params = [current_user.id]

    if start_date:
        query += " AND date >= ?"
        params.append(start_date)

    if end_date:
        query += " AND date <= ?"
        params.append(end_date)

    if category:
        query += " AND category = ?"
        params.append(category)

    if min_amount:
        query += " AND amount >= ?"
        params.append(float(min_amount))

    if max_amount:
        query += " AND amount <= ?"
        params.append(float(max_amount))

    query += " ORDER BY date DESC"

    expenses = conn.execute(query, params).fetchall()
    # Get all distinct categories for the dropdown
    all_cats = get_all_categories(conn, current_user.id)
    
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