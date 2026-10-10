import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from connection import get_db_connection

app = Flask(__name__)
app.config['SECRET_KEY'] = '3306'

# ==========================================
# CONFIGURATIONS & HELPERS
# ==========================================
UPLOAD_FOLDER = 'static/uploads/books'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Access denied! This page is restricted to administrators only.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# ==========================================
# GLOBAL CONTEXT PROCESSOR (Navbar Data)
# ==========================================
@app.context_processor
def inject_global_data():
    cart_count = 0
    admin_notifications = []
    unread_count = 0

    if 'user_id' in session and ('role' not in session or session.get('role') != 'admin'):
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT SUM(quantity) as total FROM cart WHERE user_id = %s", (session['user_id'],))
            result = cursor.fetchone()
            if result and result['total']:
                cart_count = result['total']
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Cart Count Error: {e}")

    # ទាញយក Notifications សម្រាប់ Admin
    if 'role' in session and session['role'] == 'admin':
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT 10")
            admin_notifications = cursor.fetchall()

            cursor.execute("SELECT COUNT(*) as count FROM notifications WHERE is_read = 0")
            res = cursor.fetchone()
            if res:
                unread_count = res['count']
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Admin Notification Error: {e}")

    return dict(
        cart_count=cart_count,
        admin_notifications=admin_notifications,
        unread_count=unread_count
    )


# ==========================================
# 1. AUTHENTICATION ROUTES (Register, Login, Logout)
# ==========================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not username or not email or not password:
            flash('Please fill in all required fields!', 'danger')
            return redirect(url_for('register'))

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                flash('This email is already in use!', 'danger')
                return redirect(url_for('register'))

            hashed_password = generate_password_hash(password)
            role = 'user'

            cursor.execute(
                "INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s)",
                (username, email, hashed_password, role)
            )
            conn.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            conn.rollback()
            flash(f'An error occurred during registration: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('users/register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']

            flash(f'Welcome back, {user["username"]}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password!', 'danger')

    return render_template('users/login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully!', 'success')
    return redirect(url_for('index'))


# ==========================================
# 2. BOOKS & HOME ROUTES
# ==========================================
@app.route('/')
def index():
    search_query = request.args.get('search', '').strip()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if search_query:
            sql = """
                SELECT b.*, c.name AS category_name, a.name AS author_name
                FROM books b
                LEFT JOIN categories c ON b.category_id = c.id
                LEFT JOIN authors a ON b.author_id = a.id
                WHERE b.title LIKE %s
                ORDER BY b.id DESC
            """
            cursor.execute(sql, (f"%{search_query}%",))
        else:
            sql = """
                SELECT b.*, c.name AS category_name, a.name AS author_name
                FROM books b
                LEFT JOIN categories c ON b.category_id = c.id
                LEFT JOIN authors a ON b.author_id = a.id
                ORDER BY b.id DESC
            """
            cursor.execute(sql)

        books = cursor.fetchall()
    except Exception as e:
        print(f"Search Error: {e}")
        books = []
    finally:
        cursor.close()
        conn.close()

    return render_template('books/index.html', books=books, search_query=search_query)


@app.route('/books/detail/<int:id>')
def detail_book(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT books.*, categories.name AS category_name, authors.name AS author_name
        FROM books
        LEFT JOIN categories ON books.category_id = categories.id
        LEFT JOIN authors ON books.author_id = authors.id
        WHERE books.id = %s
    """
    cursor.execute(query, (id,))
    book = cursor.fetchone()

    cursor.close()
    conn.close()

    if not book:
        flash('Book not found!', 'danger')
        return redirect(url_for('index'))

    return render_template('books/detail.html', book=book)


@app.route('/books/create', methods=['GET', 'POST'])
@admin_required
def create_book():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        category_input = request.form.get('category_input', '').strip()
        author_input = request.form.get('author_input', '').strip()
        price = request.form.get('price', 0)
        stock = request.form.get('stock', 0)
        isbn = request.form.get('isbn', '').strip()
        description = request.form.get('description', '').strip()

        try:
            category_id = None
            if category_input:
                cursor.execute("SELECT id FROM categories WHERE name = %s", (category_input,))
                cat = cursor.fetchone()
                if cat:
                    category_id = cat['id']
                else:
                    cursor.execute("INSERT INTO categories (name) VALUES (%s)", (category_input,))
                    conn.commit()
                    category_id = cursor.lastrowid

            author_id = None
            if author_input:
                cursor.execute("SELECT id FROM authors WHERE name = %s", (author_input,))
                aut = cursor.fetchone()
                if aut:
                    author_id = aut['id']
                else:
                    cursor.execute("INSERT INTO authors (name) VALUES (%s)", (author_input,))
                    conn.commit()
                    author_id = cursor.lastrowid

            filename = 'default.jpg'
            if 'cover_image' in request.files:
                file = request.files['cover_image']
                if file and file.filename != '' and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            insert_query = """
                INSERT INTO books (title, category_id, author_id, price, stock, isbn, cover_image, description)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, (title, category_id, author_id, price, stock, isbn, filename, description))
            conn.commit()

            flash('Book added successfully!', 'success')
            return redirect(url_for('index'))

        except Exception as e:
            conn.rollback()
            print(f"INSERT ERROR: {e}")
            flash(f'Failed to add book. Please try again!: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()

    try:
        cursor.execute("SELECT name FROM categories ORDER BY name ASC")
        categories = cursor.fetchall()
        cursor.execute("SELECT name FROM authors ORDER BY name ASC")
        authors = cursor.fetchall()
    except Exception:
        categories = []
        authors = []
    finally:
        cursor.close()
        conn.close()

    return render_template('books/create.html', categories=categories, authors=authors)


@app.route('/books/update/<int:id>', methods=['GET', 'POST'])
@admin_required
def update_book(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        title = request.form['title']
        category_input = request.form['category'].strip()
        author_input = request.form['author'].strip() if request.form.get('author') else None
        price = request.form['price']
        stock = request.form['stock']
        isbn = request.form['isbn']
        description = request.form['description']

        cursor.execute("SELECT id FROM categories WHERE name = %s", (category_input,))
        category = cursor.fetchone()
        if category:
            category_id = category['id']
        else:
            cursor.execute("INSERT INTO categories (name) VALUES (%s)", (category_input,))
            conn.commit()
            category_id = cursor.lastrowid

        author_id = None
        if author_input:
            cursor.execute("SELECT id FROM authors WHERE name = %s", (author_input,))
            author = cursor.fetchone()
            if author:
                author_id = author['id']
            else:
                cursor.execute("INSERT INTO authors (name) VALUES (%s)", (author_input,))
                conn.commit()
                author_id = cursor.lastrowid

        cursor.execute("SELECT cover_image FROM books WHERE id = %s", (id,))
        old_book = cursor.fetchone()
        filename = old_book['cover_image'] if old_book else 'default.jpg'

        if 'cover_image' in request.files:
            file = request.files['cover_image']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        update_query = """
            UPDATE books
            SET title = %s, category_id = %s, author_id = %s, price = %s, stock = %s, isbn = %s, cover_image = %s, description = %s
            WHERE id = %s
        """
        cursor.execute(update_query, (title, category_id, author_id, price, stock, isbn, filename, description, id))
        conn.commit()

        cursor.close()
        conn.close()
        flash('Book updated successfully!', 'success')
        return redirect(url_for('index'))

    cursor.execute("SELECT * FROM books WHERE id = %s", (id,))
    book = cursor.fetchone()
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()
    cursor.execute("SELECT * FROM authors")
    authors = cursor.fetchall()

    cursor.close()
    conn.close()

    if not book:
        flash('Book not found!', 'danger')
        return redirect(url_for('index'))

    return render_template('books/update.html', book=book, categories=categories, authors=authors)


@app.route('/books/delete/<int:id>', methods=['POST'])
@admin_required
def delete_book(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT cover_image FROM books WHERE id = %s", (id,))
    book = cursor.fetchone()
    if book and book['cover_image'] and book['cover_image'] != 'default.jpg':
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], book['cover_image'])
        if os.path.exists(image_path):
            os.remove(image_path)

    cursor.execute("DELETE FROM books WHERE id = %s", (id,))
    conn.commit()

    cursor.close()
    conn.close()
    flash('Book deleted successfully!', 'success')
    return redirect(url_for('index'))


# ==========================================
# 3. CART & CHECKOUT ROUTES
# ==========================================
@app.route('/cart/add', methods=['POST'])
def add_to_cart():
    if 'user_id' not in session:
        flash('Please log in first!', 'warning')
        return redirect(url_for('login'))

    user_id = session['user_id']
    book_id = request.form.get('book_id')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM cart WHERE user_id = %s AND book_id = %s", (user_id, book_id))
        existing_item = cursor.fetchone()

        if existing_item:
            cursor.execute("UPDATE cart SET quantity = quantity + 1 WHERE user_id = %s AND book_id = %s", (user_id, book_id))
        else:
            cursor.execute("INSERT INTO cart (user_id, book_id, quantity) VALUES (%s, %s, 1)", (user_id, book_id))

        conn.commit()
        flash('Book added to cart successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'An error occurred: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('view_cart'))


@app.route('/cart')
def view_cart():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT c.*, b.title, b.price
        FROM cart c
        JOIN books b ON c.book_id = b.id
        WHERE c.user_id = %s
    """, (session['user_id'],))
    cart_items = cursor.fetchall()

    total_amount = sum(item['price'] * item['quantity'] for item in cart_items)

    cursor.close()
    conn.close()

    return render_template('orders/cart.html', cart_items=cart_items, total_amount=total_amount)


@app.route('/cart/checkout', methods=['POST'])
def cart_checkout():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT c.*, b.price, b.stock
            FROM cart c
            JOIN books b ON c.book_id = b.id
            WHERE c.user_id = %s
        """, (user_id,))
        cart_items = cursor.fetchall()

        if not cart_items:
            flash('Your cart is empty!', 'warning')
            return redirect(url_for('view_cart'))

        total_price = sum(item['price'] * item['quantity'] for item in cart_items)

        # 1. បង្កើត Order ថ្មី
        cursor.execute("""
            INSERT INTO orders (user_id, total_price, status, payment_status, created_at)
            VALUES (%s, %s, 'Pending', 'Unpaid', NOW())
        """, (user_id, total_price))
        order_id = cursor.lastrowid

        # 2. បង្កើត Notification ជូនដំណឹងដល់ Admin
        message = f"There is a new order (Order ID: {order_id})"
        cursor.execute("""
            INSERT INTO notifications (message, is_read, created_at)
            VALUES (%s, 0, NOW())
        """, (message,))

        # 3. បញ្ចូល order_items និងកាត់ស្តុកសៀវភៅ
        for item in cart_items:
            cursor.execute("""
                INSERT INTO order_items (order_id, book_id, quantity, price)
                VALUES (%s, %s, %s, %s)
            """, (order_id, item['book_id'], item['quantity'], item['price']))

            cursor.execute("""
                UPDATE books SET stock = stock - %s WHERE id = %s
            """, (item['quantity'], item['book_id']))

        # 4. សម្អាត Cart របស់ User ចេញ
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        conn.commit()

    except Exception as e:
        conn.rollback()
        print(f"Cart Checkout Error: {e}")
        flash(f'An error occurred while processing your order: {e}', 'danger')
        return redirect(url_for('view_cart'))
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('payment', order_id=order_id))


# (Optional Direct Checkout for single book if needed)
@app.route('/checkout', methods=['POST'])
def checkout():
    if 'user_id' not in session:
        flash('Please log in first!', 'danger')
        return redirect(url_for('login'))

    user_id = session['user_id']
    book_id = request.form.get('book_id')
    quantity = int(request.form.get('quantity', 1))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT price, stock FROM books WHERE id = %s", (book_id,))
        book = cursor.fetchone()

        if not book:
            flash('Book not found!', 'danger')
            return redirect(url_for('index'))

        if book['stock'] < quantity:
            flash('Book out of stock!', 'warning')
            return redirect(url_for('index'))

        total_price = float(book['price']) * quantity

        cursor.execute(
            "INSERT INTO orders (user_id, total_price, status, payment_status, created_at) VALUES (%s, %s, %s, %s, NOW())",
            (user_id, total_price, 'Pending', 'Unpaid')
        )
        order_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO order_items (order_id, book_id, quantity, price) VALUES (%s, %s, %s, %s)",
            (order_id, book_id, quantity, book['price'])
        )

        cursor.execute(
            "UPDATE books SET stock = stock - %s WHERE id = %s",
            (quantity, book_id)
        )

        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f'An error occurred while processing your order: {e}', 'danger')
        return redirect(url_for('index'))
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('payment', order_id=order_id))


# ==========================================
# 4. ORDERS & PAYMENT ROUTES
# ==========================================
@app.route('/orders')
def orders():
    if 'user_id' not in session:
        flash('Please log in first!', 'warning')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if session.get('role') == 'admin':
            cursor.execute("""
                SELECT o.*, u.username
                FROM orders o
                JOIN users u ON o.user_id = u.id
                ORDER BY o.created_at DESC
            """)
        else:
            cursor.execute("""
                SELECT * FROM orders
                WHERE user_id = %s
                ORDER BY created_at DESC
            """, (session['user_id'],))

        orders_list = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching orders: {e}")
        orders_list = []
    finally:
        cursor.close()
        conn.close()

    return render_template('orders/index.html', orders=orders_list)


@app.route('/orders/<int:order_id>')
def order_detail(order_id):
    if 'user_id' not in session:
        flash('Please log in first!', 'warning')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    order = None
    items = []

    try:
        if session.get('role') == 'admin':
            cursor.execute("""
                SELECT o.*, u.username, u.email
                FROM orders o
                JOIN users u ON o.user_id = u.id
                WHERE o.id = %s
            """, (order_id,))
        else:
            cursor.execute("""
                SELECT o.*, u.username, u.email
                FROM orders o
                JOIN users u ON o.user_id = u.id
                WHERE o.id = %s AND o.user_id = %s
            """, (order_id, session['user_id']))

        order = cursor.fetchone()

        if order is None:
            flash('Order not found or you do not have permission to view it!', 'danger')
            return redirect(url_for('orders'))

        cursor.execute("""
            SELECT oi.*, b.title
            FROM order_items oi
            JOIN books b ON oi.book_id = b.id
            WHERE oi.order_id = %s
        """, (order_id,))
        items = cursor.fetchall()

    except Exception as e:
        print(f"Error fetching order detail: {e}")
        flash(f'An error occurred while fetching order detail: {e}', 'danger')
        return redirect(url_for('orders'))
    finally:
        cursor.close()
        conn.close()

    return render_template('orders/detail.html', order=order, items=items)


@app.route('/payment/<int:order_id>')
def payment(order_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM orders WHERE id = %s AND user_id = %s", (order_id, session['user_id']))
    order = cursor.fetchone()
    cursor.close()
    conn.close()

    if not order:
        flash('Order not found!', 'danger')
        return redirect(url_for('index'))

    return render_template('orders/payment.html', order=order)


@app.route('/confirm-payment/<int:order_id>', methods=['POST'])
def confirm_payment(order_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET payment_status = 'Paid', status = 'Processing' WHERE id = %s", (order_id,))
    conn.commit()
    cursor.close()
    conn.close()

    flash('Payment successful!', 'success')
    return redirect(url_for('order_detail', order_id=order_id))


# ==========================================
# 5. NOTIFICATION ROUTES
# ==========================================
@app.route('/notification/read/<int:id>')
def read_notification(id):
    if 'role' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = %s", (id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f'An error occurred while reading the notification: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('orders'))


# ==========================================
# 6. CATEGORIES ROUTES
# ==========================================
@app.route('/categories')
def index_category():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM categories ORDER BY id DESC")
    categories = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('categories/index.html', categories=categories)


@app.route('/categories/create', methods=['GET', 'POST'])
@admin_required
def create_category():
    if request.method == 'POST':
        name = request.form.get('name')
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO categories (name) VALUES (%s)", (name,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Category added successfully!', 'success')
        return redirect(url_for('index_category'))

    return render_template('categories/create.html')


@app.route('/categories/update/<int:id>', methods=['GET', 'POST'])
@admin_required
def update_category(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        name = request.form.get('name')
        cursor.execute("UPDATE categories SET name = %s WHERE id = %s", (name, id))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Category updated successfully!', 'success')
        return redirect(url_for('index_category'))

    cursor.execute("SELECT * FROM categories WHERE id = %s", (id,))
    category = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('categories/update.html', category=category)


@app.route('/categories/delete/<int:id>', methods=['POST'])
@admin_required
def delete_category(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM categories WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Category deleted successfully!', 'danger')
    return redirect(url_for('index_category'))


# ==========================================
# RUN APPLICATION
# ==========================================
if __name__ == '__main__':
    app.run(debug=True)
