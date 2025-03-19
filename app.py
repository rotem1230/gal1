from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, make_response, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from fpdf import FPDF
import arabic_reshaper
from bidi.algorithm import get_display
import os.path
from flask_migrate import Migrate
import pandas as pd
import zipfile

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# מודלים של מסד הנתונים
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    image = db.Column(db.String(200))
    products = db.relationship('Product', backref='category', lazy=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price_without_vat = db.Column(db.Float, nullable=False)
    price_with_vat = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(200))
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    variations = db.relationship('ProductVariation', backref='product', lazy=True)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(300))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    orders = db.relationship('Order', backref='customer', lazy=True)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))  # קשר ללקוח
    total_without_vat = db.Column(db.Float, nullable=False)
    total_with_vat = db.Column(db.Float, nullable=False)
    items = db.relationship('OrderItem', backref='order', lazy=True)

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price_without_vat = db.Column(db.Float, nullable=False)
    price_with_vat = db.Column(db.Float, nullable=False)
    product_name = db.Column(db.String(100), nullable=False)  # שומרים את שם המוצר בזמן ההזמנה

# הוספת מודל חדש
class ProductVariation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)  # שם הווריאציה (למשל: "אבטיח", "מלון")
    price_without_vat = db.Column(db.Float, nullable=False)
    price_with_vat = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(200))

# יצירת מסד הנתונים והמשתמש הראשון
def init_db():
    with app.app_context():
        # יצירת טבלאות חדשות בלבד (לא מוחק קיימות)
        db.create_all()
        
        # בדיקה אם יש משתמש במערכת
        if not User.query.first():
            # יצירת משתמש ראשון
            admin_user = User(
                username='admin',
                password=generate_password_hash('admin123')
            )
            try:
                db.session.add(admin_user)
                db.session.commit()
                print("משתמש מנהל נוצר בהצלחה")
            except Exception as e:
                print(f"שגיאה ביצירת משתמש: {e}")
                db.session.rollback()

# בדיקה אם מסד הנתונים קיים
if not os.path.exists('instance/inventory.db'):
    init_db()
else:
    # אם מסד הנתונים קיים, רק מוסיף טבלאות חדשות
    with app.app_context():
        db.create_all()

# וידוא שתיקיית ההעלאות קיימת
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
    print(f"נוצרה תיקיית העלאות: {app.config['UPLOAD_FOLDER']}")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if not user:
            flash('שם משתמש לא קיים')
            return render_template('login.html')
        
        if not check_password_hash(user.password, password):
            flash('סיסמה שגויה')
            return render_template('login.html')
        
        session['user_id'] = user.id
        return redirect(url_for('products'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/')
@app.route('/products')
def products():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # קבלת פרמטרים לחיפוש וסינון
    search_query = request.args.get('search', '')
    category_filter = request.args.get('category', '')
    sort_by = request.args.get('sort', 'name')
    
    # שליפת המוצרים עם פילטרים
    products_query = Product.query
    
    if search_query:
        products_query = products_query.filter(Product.name.ilike(f'%{search_query}%'))
    
    if category_filter:
        products_query = products_query.filter(Product.category_id == category_filter)
    
    # מיון
    if sort_by == 'price_asc':
        products_query = products_query.order_by(Product.price_with_vat.asc())
    elif sort_by == 'price_desc':
        products_query = products_query.order_by(Product.price_with_vat.desc())
    else:  # sort_by == 'name'
        products_query = products_query.order_by(Product.name.asc())
    
    products = products_query.all()
    categories = Category.query.all()
    
    return render_template('products.html', 
                         products=products, 
                         categories=categories,
                         search_query=search_query,
                         category_filter=category_filter,
                         sort_by=sort_by)

@app.route('/add-product', methods=['POST'])
def add_product():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    name = request.form['name']
    price_with_vat = float(request.form['price_with_vat'])
    price_without_vat = price_with_vat / 1.18  # חישוב מחיר ללא מע"מ
    category_id = int(request.form['category_id'])
    
    image_filename = None
    if 'image' in request.files:
        file = request.files['image']
        if file and allowed_file(file.filename):
            # יצירת שם קובץ ייחודי עם חותמת זמן ומזהה מוצר
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"product_{timestamp}_{secure_filename(file.filename)}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_filename = filename

    product = Product(
        name=name,
        price_without_vat=price_without_vat,
        price_with_vat=price_with_vat,
        category_id=category_id,
        image=image_filename
    )
    
    db.session.add(product)
    db.session.commit()
    
    return redirect(url_for('products'))

@app.route('/add-to-cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    data = request.get_json()
    quantity = int(data.get('quantity', 1))
    variation_id = data.get('variation_id')
    price_with_vat = data.get('price_with_vat')
    price_without_vat = data.get('price_without_vat')
    
    if quantity < 1:
        return jsonify({'success': False, 'message': 'כמות חייבת להיות לפחות 1'})
    
    product = Product.query.get_or_404(product_id)
    
    # אם למוצר יש וריאציות, חייבים לבחור אחת
    if product.variations and not variation_id:
        return jsonify({'success': False, 'message': 'נא לבחור וריאציה'})
    
    if 'cart' not in session:
        session['cart'] = []
    
    cart_item = {
        'product_id': product_id,
        'quantity': quantity,
        'variation_id': variation_id,
        'price_with_vat': price_with_vat if variation_id else product.price_with_vat,
        'price_without_vat': price_without_vat if variation_id else product.price_without_vat
    }
    
    cart = session['cart']
    # מוסיף את המוצר לסל מספר פעמים לפי הכמות שנבחרה
    for _ in range(quantity):
        cart.append(cart_item)
    
    session['cart'] = cart
    
    return jsonify({
        'success': True, 
        'message': f'{quantity} יחידות נוספו להזמנה בהצלחה'
    })

@app.route('/categories')
def categories():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    categories = Category.query.all()
    return render_template('categories.html', categories=categories)

@app.route('/add-category', methods=['POST'])
def add_category():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    name = request.form['name']
    
    # וודא שתיקיית ההעלאות קיימת
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    
    image_filename = None
    if 'image' in request.files:
        file = request.files['image']
        if file and allowed_file(file.filename):
            # יצירת שם קובץ ייחודי עם חותמת זמן
            filename = f"category_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_filename = filename

    try:
        category = Category(name=name, image=image_filename)
        db.session.add(category)
        db.session.commit()
        flash('הקטגוריה נוצרה בהצלחה', 'success')
    except Exception as e:
        flash('אירעה שגיאה ביצירת הקטגוריה', 'error')
        return redirect(url_for('categories'))
    
    return redirect(url_for('categories'))

@app.route('/category/<int:category_id>')
def category_products(category_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    category = Category.query.get_or_404(category_id)
    return render_template('category_products.html', category=category)

@app.route('/cart')
def cart():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if 'cart' not in session:
        session['cart'] = []
    
    cart_items = []
    total_without_vat = 0
    total_with_vat = 0
    
    # מקבץ פריטים זהים בסל
    cart_items_dict = {}
    for item in session['cart']:
        key = (item['product_id'], item.get('variation_id'))
        if key not in cart_items_dict:
            cart_items_dict[key] = {
                'product_id': item['product_id'],
                'variation_id': item.get('variation_id'),
                'quantity': 0,
                'price_with_vat': item['price_with_vat'],
                'price_without_vat': item['price_without_vat']
            }
        cart_items_dict[key]['quantity'] += 1
    
    # יצירת רשימת פריטים עם מחירים נכונים
    for key, item_data in cart_items_dict.items():
        product = Product.query.get(item_data['product_id'])
        if product:
            variation = None
            if item_data['variation_id']:
                variation = ProductVariation.query.get(item_data['variation_id'])
            
            quantity = item_data['quantity']
            price_with_vat = item_data['price_with_vat']
            price_without_vat = item_data['price_without_vat']
            
            total_without_vat += price_without_vat * quantity
            total_with_vat += price_with_vat * quantity
            
            cart_items.append({
                'product': product,
                'variation': variation,
                'quantity': quantity,
                'price_with_vat': price_with_vat,
                'price_without_vat': price_without_vat,
                'total_without_vat': price_without_vat * quantity,
                'total_with_vat': price_with_vat * quantity
            })
    
    customers = Customer.query.order_by(Customer.name).all()
    return render_template('cart.html', 
                         cart_items=cart_items,
                         total_without_vat=total_without_vat,
                         total_with_vat=total_with_vat,
                         customers=customers)

@app.route('/update-cart/<int:product_id>', methods=['POST'])
def update_cart(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    data = request.get_json()
    quantity = int(data['quantity'])
    
    cart = []
    for _ in range(quantity):
        cart.append(product_id)
    
    session['cart'] = cart
    return jsonify({'success': True, 'message': 'הכמות עודכנה בהצלחה'})

@app.route('/remove-from-cart/<int:product_id>', methods=['POST'])
def remove_from_cart(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    cart = session['cart']
    cart = [p for p in cart if p != product_id]
    session['cart'] = cart
    
    return jsonify({'success': True, 'message': 'המוצר הוסר בהצלחה'})

@app.route('/clear-cart', methods=['POST'])
def clear_cart():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    session['cart'] = []
    return jsonify({'success': True, 'message': 'סל ההזמנות נוקה בהצלחה'})

@app.route('/export-pdf')
def export_pdf():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    export_type = request.args.get('type', 'warehouse')
    order_id = request.args.get('order_id')  # מזהה הזמנה קיימת
    is_warehouse = export_type == 'warehouse'
    
    if order_id:
        # מייצא הזמנה קיימת
        order = Order.query.get_or_404(order_id)
        customer = order.customer
        cart_items = []
        
        for item in order.items:
            cart_items.append({
                'product': Product(name=item.product_name),
                'quantity': item.quantity,
                'total_without_vat': item.price_without_vat * item.quantity,
                'total_with_vat': item.price_with_vat * item.quantity
            })
        
        total_without_vat = order.total_without_vat
        total_with_vat = order.total_with_vat
        
        # אין צורך לשמור את ההזמנה כי היא כבר קיימת
        save_order = False
    else:
        # יצירת הזמנה חדשה
        customer_id = request.args.get('customer_id')
        if not customer_id:
            return jsonify({'success': False, 'message': 'לא נבחר לקוח'})
        
        customer = Customer.query.get_or_404(customer_id)
        
        if 'cart' not in session:
            session['cart'] = []
        
        cart_items = []
        total_without_vat = 0
        total_with_vat = 0
        
        # מקבץ פריטים זהים בסל
        cart_items_dict = {}
        for item in session['cart']:
            key = (item['product_id'], item.get('variation_id'))
            if key not in cart_items_dict:
                cart_items_dict[key] = {
                    'product_id': item['product_id'],
                    'variation_id': item.get('variation_id'),
                    'quantity': 0,
                    'price_with_vat': item['price_with_vat'],
                    'price_without_vat': item['price_without_vat']
                }
            cart_items_dict[key]['quantity'] += 1
        
        # יצירת רשימת פריטים עם מחירים נכונים
        for key, item_data in cart_items_dict.items():
            product = Product.query.get(item_data['product_id'])
            if product:
                variation = None
                if item_data['variation_id']:
                    variation = ProductVariation.query.get(item_data['variation_id'])
                
                quantity = item_data['quantity']
                price_with_vat = item_data['price_with_vat']
                price_without_vat = item_data['price_without_vat']
                
                total_without_vat += price_without_vat * quantity
                total_with_vat += price_with_vat * quantity
                
                cart_items.append({
                    'product': product,
                    'variation': variation,
                    'quantity': quantity,
                    'total_without_vat': price_without_vat * quantity,
                    'total_with_vat': price_with_vat * quantity
                })
        
        # צריך לשמור הזמנה חדשה
        save_order = True
    
    # יצירת PDF
    pdf = FPDF()
    pdf.add_page()
    
    # הגדרת פונט
    font_path = os.path.join(app.root_path, 'fonts', 'DejaVuSansCondensed.ttf')
    pdf.add_font('DejaVu', '', font_path, uni=True)
    pdf.set_font('DejaVu', '', 12)
    
    # לוגו בצד ימין
    try:
        # בדיקה בתיקיית static/images
        logo_path = os.path.join(app.root_path, 'static', 'images', 'logo.png')
        if not os.path.exists(logo_path):
            # בדיקה בתיקיית uploads
            logo_path = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], 'logo.png')
        
        if os.path.exists(logo_path):
            pdf.image(logo_path, x=10, y=10, w=50)
        else:
            print(f"קובץ הלוגו לא נמצא בנתיבים: {os.path.join(app.root_path, 'static', 'images', 'logo.png')} או {os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], 'logo.png')}")
    except Exception as e:
        print(f"שגיאה בטעינת הלוגו: {e}")
    
    # תאריך בצד שמאל עליון
    pdf.set_xy(150, 10)
    current_date = datetime.now().strftime('%d/%m/%Y')
    pdf.cell(50, 10, get_display(arabic_reshaper.reshape(f'תאריך: {current_date}')), align='L')
    
    # פרטי לקוח מתחת ללוגו
    pdf.set_xy(10, 40)
    pdf.set_font('DejaVu', '', 14)
    pdf.cell(0, 10, get_display(arabic_reshaper.reshape(f'לכבוד: {customer.name}')), ln=True, align='R')
    if customer.address:
        pdf.cell(0, 10, get_display(arabic_reshaper.reshape(f'כתובת: {customer.address}')), ln=True, align='R')
    if customer.phone:
        pdf.cell(0, 10, get_display(arabic_reshaper.reshape(f'טלפון: {customer.phone}')), ln=True, align='R')
    pdf.ln(10)
    
    # כותרת הזמנה
    pdf.set_font('DejaVu', '', 16)
    pdf.cell(0, 10, get_display(arabic_reshaper.reshape('הזמנה')), ln=True, align='C')
    pdf.ln(10)
    
    # טבלת מוצרים
    pdf.set_font('DejaVu', '', 12)
    
    # כותרות העמודות
    if is_warehouse:
        col_widths = [60, 25, 35, 35, 35]  # רוחב העמודות
        headers = ['מוצר', 'כמות', 'מחיר ליח׳', 'מחיר כולל', 'סה"כ']
        subheaders = ['', '', 'ללא מע"מ', 'מע"מ', '']
    else:
        # גרסת לקוח - רק שם מוצר וכמות
        col_widths = [150, 40]  # רוחב עמודות מותאם
        headers = ['מוצר', 'כמות']
        subheaders = None
    
    # יצירת טבלה
    pdf.set_fill_color(240, 240, 240)

    # חישוב הרוחב הכולל של הטבלה
    total_width = sum(col_widths)
    x_start = pdf.w - total_width - 10  # התחלה מהצד הימני

    # הדפסת כותרות ראשיות
    current_x = x_start
    for header, width in zip(headers, col_widths):
        pdf.set_x(current_x)
        pdf.cell(width, 8, get_display(arabic_reshaper.reshape(header)), border=1, align='C', fill=True)
        current_x += width
    pdf.ln()

    # הדפסת תת-כותרות אם יש
    if subheaders:
        current_x = x_start
        for subheader, width in zip(subheaders, col_widths):
            pdf.set_x(current_x)
            pdf.cell(width, 8, get_display(arabic_reshaper.reshape(subheader)), border=1, align='C', fill=True)
            current_x += width
        pdf.ln()

    # תוכן הטבלה
    for item in cart_items:
        current_x = x_start
        
        if is_warehouse:
            price_per_unit_without_vat = item['total_without_vat'] / item['quantity']
            price_per_unit_with_vat = item['total_with_vat'] / item['quantity']
            
            product_name = item['product'].name
            if item.get('variation'):
                product_name += f" ({item['variation'].name})"
            
            cells = [
                product_name,
                str(item['quantity']),
                f"₪{price_per_unit_without_vat:.2f}",
                f"₪{price_per_unit_with_vat:.2f}",
                f"₪{item['total_with_vat']:.2f}"
            ]
        else:
            # גרסת לקוח - רק שם מוצר וכמות
            product_name = item['product'].name
            if item.get('variation'):
                product_name += f" ({item['variation'].name})"
            
            cells = [
                product_name,
                str(item['quantity'])
            ]
        
        # הדפסת תאים בשורה
        for cell, width in zip(cells, col_widths):
            pdf.set_x(current_x)
            pdf.cell(width, 10, get_display(arabic_reshaper.reshape(cell)), border=1, align='C')
            current_x += width
        pdf.ln()
    
    # סיכום - רק בגרסת מחסן
    if is_warehouse:
        pdf.ln(10)
        pdf.set_x(120)
        pdf.cell(40, 10, get_display(arabic_reshaper.reshape('סה"כ ללא מע"מ:')), align='R')
        pdf.cell(30, 10, get_display(arabic_reshaper.reshape(f'₪{total_without_vat:.2f}')), align='L')
        pdf.ln()
        
        pdf.set_x(120)
        pdf.cell(40, 10, get_display(arabic_reshaper.reshape('מע"מ:')), align='R')
        pdf.cell(30, 10, get_display(arabic_reshaper.reshape(f'₪{(total_with_vat - total_without_vat):.2f}')), align='L')
        pdf.ln()
        
        pdf.set_x(120)
        pdf.set_font('DejaVu', '', 14)
        pdf.cell(40, 10, get_display(arabic_reshaper.reshape('סה"כ כולל מע"מ:')), align='R')
        pdf.cell(30, 10, get_display(arabic_reshaper.reshape(f'₪{total_with_vat:.2f}')), align='L')
    
    # שמירה והחזרה
    pdf_output = pdf.output(dest='S').encode('latin-1')
    response = make_response(pdf_output)
    response.headers['Content-Type'] = 'application/pdf'
    
    # שם קובץ שונה לכל סוג
    filename = 'warehouse_order.pdf' if is_warehouse else 'customer_order.pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    
    # שמירת ההזמנה במסד הנתונים רק אם זו הזמנה חדשה
    if save_order:
        order = Order(
            customer_id=customer.id,
            total_without_vat=total_without_vat,
            total_with_vat=total_with_vat
        )
        db.session.add(order)
        
        for item in cart_items:
            order_item = OrderItem(
                order=order,
                product_id=item['product'].id,
                quantity=item['quantity'],
                price_without_vat=item['total_without_vat'] / item['quantity'],
                price_with_vat=item['total_with_vat'] / item['quantity'],
                product_name=item['product'].name + (f" ({item['variation'].name})" if item.get('variation') else "")
            )
            db.session.add(order_item)
        
        db.session.commit()
    
    return response

@app.route('/finish-order', methods=['POST'])
def finish_order():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    data = request.get_json()
    customer_id = data.get('customer_id')
    
    if not customer_id:
        return jsonify({'success': False, 'message': 'לא נבחר לקוח'})
    
    # בדיקה שהלקוח קיים
    customer = Customer.query.get(customer_id)
    if not customer:
        return jsonify({'success': False, 'message': 'לקוח לא נמצא'})
    
    session['cart'] = []
    return jsonify({
        'success': True, 
        'message': 'ההזמנה הושלמה בהצלחה והסל נוקה'
    })

@app.route('/edit-product/<int:product_id>', methods=['POST'])
def edit_product(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    product = Product.query.get_or_404(product_id)
    
    try:
        product.name = request.form['name']
        price_with_vat = float(request.form['price_with_vat'])
        product.price_without_vat = price_with_vat / 1.18  # חישוב מחיר ללא מע"מ
        product.price_with_vat = price_with_vat
        product.category_id = int(request.form['category_id'])
        
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                # מחיקת התמונה הישנה אם קיימת
                if product.image:
                    old_image_path = os.path.join(app.config['UPLOAD_FOLDER'], product.image)
                    if os.path.exists(old_image_path):
                        os.remove(old_image_path)
                
                # יצירת שם קובץ ייחודי עם חותמת זמן ומזהה מוצר
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"product_{product_id}_{timestamp}_{secure_filename(file.filename)}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                product.image = filename
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'המוצר עודכן בהצלחה'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'אירעה שגיאה בעדכון המוצר'})

@app.route('/delete-product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    product = Product.query.get_or_404(product_id)
    print(f"DEBUG: Trying to delete product {product_id}")
    
    try:
        # בדיקה אם המוצר קיים בהזמנות
        order_items = OrderItem.query.filter_by(product_id=product_id).all()  # שינוי ל-all() במקום first()
        print(f"DEBUG: Found {len(order_items)} order items for product {product_id}")
        
        if order_items:
            print(f"DEBUG: Order items details: {[{'order_id': item.order_id, 'quantity': item.quantity} for item in order_items]}")
            return jsonify({
                'success': False, 
                'message': 'לא ניתן למחוק מוצר שקיים בהזמנות. יש למחוק קודם את ההזמנות הרלוונטיות'
            })
        
        # בדיקה אם המוצר נמצא בסל הקניות הנוכחי
        if 'cart' in session:
            cart_items = [item for item in session['cart'] if item['product_id'] == product_id]
            print(f"DEBUG: Found {len(cart_items)} cart items for product {product_id}")
            if cart_items:
                return jsonify({
                    'success': False,
                    'message': 'לא ניתן למחוק מוצר שנמצא בסל הקניות. יש לנקות את הסל קודם'
                })
        
        # מחיקת כל הווריאציות של המוצר
        variations = ProductVariation.query.filter_by(product_id=product_id).all()
        print(f"DEBUG: Found {len(variations)} variations for product {product_id}")
        ProductVariation.query.filter_by(product_id=product_id).delete()
        
        # מחיקת תמונת המוצר אם קיימת
        if product.image:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], product.image)
            print(f"DEBUG: Checking for image at {image_path}")
            if os.path.exists(image_path):
                os.remove(image_path)
                print("DEBUG: Image deleted")
        
        # מחיקת המוצר עצמו
        db.session.delete(product)
        db.session.commit()
        print("DEBUG: Product deleted successfully")
        return jsonify({'success': True, 'message': 'המוצר נמחק בהצלחה'})
    
    except Exception as e:
        print(f"DEBUG: Error = {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'message': f'אירעה שגיאה במחיקת המוצר: {str(e)}'})

@app.route('/edit-category/<int:category_id>', methods=['POST'])
def edit_category(category_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    category = Category.query.get_or_404(category_id)
    
    try:
        category.name = request.form['name']
        
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                # מחיקת התמונה הישנה אם קיימת
                if category.image:
                    old_image_path = os.path.join(app.config['UPLOAD_FOLDER'], category.image)
                    if os.path.exists(old_image_path):
                        os.remove(old_image_path)
                
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                category.image = filename
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'הקטגוריה עודכנה בהצלחה'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'אירעה שגיאה בעדכון הקטגוריה'})

@app.route('/delete-category/<int:category_id>', methods=['POST'])
def delete_category(category_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    category = Category.query.get_or_404(category_id)
    
    try:
        # בדיקה אם יש מוצרים בקטגוריה
        if category.products:
            return jsonify({
                'success': False, 
                'message': 'לא ניתן למחוק קטגוריה שמכילה מוצרים. יש להסיר תחילה את כל המוצרים מהקטגוריה'
            })
        
        # מחיקת תמונת הקטגוריה אם קיימת
        if category.image:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], category.image)
            if os.path.exists(image_path):
                os.remove(image_path)
        
        db.session.delete(category)
        db.session.commit()
        return jsonify({'success': True, 'message': 'הקטגוריה נמחקה בהצלחה'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'אירעה שגיאה במחיקת הקטגוריה'})

@app.route('/get-product/<int:product_id>')
def get_product(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    product = Product.query.get_or_404(product_id)
    return jsonify({
        'name': product.name,
        'price_without_vat': product.price_without_vat,
        'price_with_vat': product.price_with_vat,
        'category_id': product.category_id
    })

@app.route('/get-category/<int:category_id>')
def get_category(category_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    category = Category.query.get_or_404(category_id)
    return jsonify({
        'name': category.name
    })

def check_file_exists(filename):
    full_path = os.path.join(app.root_path, 'static', filename)
    return os.path.exists(full_path)

@app.context_processor
def utility_processor():
    return dict(check_file_exists=check_file_exists)

@app.route('/search-products')
def search_products():
    if 'user_id' not in session:
        return jsonify([])
    
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([])
    
    # חיפוש מוצרים שמתחילים או מכילים את מחרוזת החיפוש
    products = Product.query.filter(Product.name.ilike(f'%{query}%')).limit(5).all()
    
    return jsonify([{
        'id': p.id,
        'name': p.name,
        'price_with_vat': p.price_with_vat,
        'image': p.image
    } for p in products])

@app.route('/orders-history')
def orders_history():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    orders = Order.query.order_by(Order.date.desc()).all()
    return render_template('orders_history.html', orders=orders)

@app.route('/customers')
def customers():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    customers = Customer.query.order_by(Customer.name).all()
    return render_template('customers.html', customers=customers)

@app.route('/add-customer', methods=['POST'])
def add_customer():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    data = request.get_json()
    customer = Customer(
        name=data['name'],
        address=data.get('address', ''),
        phone=data.get('phone', ''),
        email=data.get('email', '')
    )
    
    try:
        db.session.add(customer)
        db.session.commit()
        return jsonify({
            'success': True,
            'message': 'הלקוח נוסף בהצלחה',
            'customer': {
                'id': customer.id,
                'name': customer.name,
                'address': customer.address,
                'phone': customer.phone,
                'email': customer.email
            }
        })
    except:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'אירעה שגיאה בהוספת הלקוח'})

@app.route('/get-customer/<int:customer_id>')
def get_customer(customer_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    customer = Customer.query.get_or_404(customer_id)
    return jsonify({
        'id': customer.id,
        'name': customer.name,
        'address': customer.address,
        'phone': customer.phone,
        'email': customer.email
    })

@app.route('/add-variation/<int:product_id>', methods=['POST'])
def add_variation(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    try:
        # בדיקה שהמוצר קיים
        product = Product.query.get_or_404(product_id)
        
        # קבלת הנתונים מהטופס
        name = request.form.get('name')
        price_without_vat = float(request.form.get('price_without_vat', 0))
        
        if not name or price_without_vat <= 0:
            return jsonify({
                'success': False, 
                'message': 'נא למלא את כל השדות הנדרשים'
            })
        
        price_with_vat = price_without_vat * 1.18  # מע"מ 18%
        
        # טיפול בתמונה
        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_filename = filename

        # יצירת הווריאציה
        variation = ProductVariation(
            product_id=product_id,
            name=name,
            price_without_vat=price_without_vat,
            price_with_vat=price_with_vat,
            image=image_filename
        )
        
        db.session.add(variation)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'הווריאציה נוספה בהצלחה',
            'variation': {
                'id': variation.id,
                'name': variation.name,
                'price_without_vat': variation.price_without_vat,
                'price_with_vat': variation.price_with_vat,
                'image': variation.image
            }
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error adding variation: {str(e)}")  # לוג של השגיאה
        return jsonify({
            'success': False, 
            'message': f'אירעה שגיאה בהוספת הווריאציה: {str(e)}'
        }), 400

@app.route('/get-variations/<int:product_id>')
def get_variations(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    product = Product.query.get_or_404(product_id)
    variations = [{
        'id': v.id,
        'name': v.name,
        'price_without_vat': v.price_without_vat,
        'price_with_vat': v.price_with_vat,
        'image': v.image
    } for v in product.variations]
    
    return jsonify(variations)

@app.route('/delete-all-products', methods=['POST'])
def delete_all_products():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    try:
        # מחיקת כל הווריאציות קודם (בגלל המפתח הזר)
        ProductVariation.query.delete()
        
        # מחיקת כל המוצרים
        Product.query.delete()
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'כל המוצרים נמחקו בהצלחה'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'שגיאה במחיקת המוצרים: {str(e)}'})

@app.route('/delete-order/<int:order_id>', methods=['POST'])
def delete_order(order_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    try:
        # מחיקת כל פריטי ההזמנה
        OrderItem.query.filter_by(order_id=order_id).delete()
        
        # מחיקת ההזמנה עצמה
        order = Order.query.get_or_404(order_id)
        db.session.delete(order)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'ההזמנה נמחקה בהצלחה'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'אירעה שגיאה במחיקת ההזמנה: {str(e)}'})

@app.route('/import-products', methods=['POST'])
def import_products():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'לא נבחר קובץ'})
    
    file = request.files['file']
    category_id = request.form.get('category_id')
    
    if file.filename == '':
        return jsonify({'success': False, 'message': 'לא נבחר קובץ'})
    
    if not file.filename.endswith('.csv'):
        return jsonify({'success': False, 'message': 'נא להעלות קובץ CSV בלבד'})
    
    try:
        # קריאת הקובץ CSV
        df = pd.read_csv(file, encoding='utf-8-sig')
        required_columns = ['name', 'price_with_vat']
        
        # בדיקת עמודות נדרשות
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return jsonify({
                'success': False, 
                'message': f'חסרות העמודות הבאות: {", ".join(missing_columns)}'
            })
        
        # ייבוא כל מוצר
        for _, row in df.iterrows():
            price_with_vat = float(row['price_with_vat'])
            price_without_vat = price_with_vat / 1.18  # חישוב מחיר ללא מע"מ
            
            # שימוש ב-category_id מהקובץ אם קיים, אחרת מהטופס
            product_category_id = row.get('category_id', category_id)
            
            # בדיקה שהקטגוריה קיימת
            if product_category_id and not Category.query.get(product_category_id):
                return jsonify({
                    'success': False,
                    'message': f'קטגוריה עם מזהה {product_category_id} לא קיימת'
                })
            
            product = Product(
                name=row['name'],
                price_without_vat=price_without_vat,
                price_with_vat=price_with_vat,
                image=row.get('image', None),  # שימוש ב-get עם ברירת מחדל
                category_id=product_category_id
            )
            db.session.add(product)
            
            # אם יש וריאציות, נוסיף אותן
            variations_columns = [col for col in df.columns if col.startswith('variation_')]
            if variations_columns:
                variation_names = [col for col in variations_columns if col.endswith('_name')]
                for var_name_col in variation_names:
                    base_name = var_name_col[:-5]  # הסרת '_name'
                    price_with_vat_col = f'{base_name}_price_with_vat'
                    
                    if pd.notna(row[var_name_col]):
                        variation_price_with_vat = float(row[price_with_vat_col])
                        variation_price_without_vat = variation_price_with_vat / 1.18  # חישוב מחיר ללא מע"מ
                        
                        variation = ProductVariation(
                            name=row[var_name_col],
                            price_without_vat=variation_price_without_vat,
                            price_with_vat=variation_price_with_vat,
                            image=row.get(f'{base_name}_image', None)  # תמונה לווריאציה אם קיימת
                        )
                        product.variations.append(variation)
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'המוצרים יובאו בהצלחה'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'אירעה שגיאה בייבוא: {str(e)}'})

@app.route('/export-all', methods=['GET'])
def export_all():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    try:
        # יצירת DataFrame של קטגוריות
        categories = Category.query.all()
        print(f"Found {len(categories)} categories")  # לוג לבדיקה
        categories_data = []
        for category in categories:
            categories_data.append({
                'id': category.id,
                'name': category.name,
                'image': category.image
            })
        categories_df = pd.DataFrame(categories_data)
        print(f"Categories DataFrame shape: {categories_df.shape}")  # לוג לבדיקה
        
        # יצירת DataFrame של מוצרים
        products = Product.query.all()
        print(f"Found {len(products)} products")  # לוג לבדיקה
        products_data = []
        for product in products:
            products_data.append({
                'id': product.id,
                'name': product.name,
                'price_with_vat': product.price_with_vat,
                'price_without_vat': product.price_without_vat,
                'image': product.image,
                'category_id': product.category_id
            })
        products_df = pd.DataFrame(products_data)
        print(f"Products DataFrame shape: {products_df.shape}")  # לוג לבדיקה
        
        # יצירת DataFrame של וריאציות
        variations = ProductVariation.query.all()
        print(f"Found {len(variations)} variations")  # לוג לבדיקה
        variations_data = []
        for variation in variations:
            variations_data.append({
                'id': variation.id,
                'product_id': variation.product_id,
                'name': variation.name,
                'price_with_vat': variation.price_with_vat,
                'price_without_vat': variation.price_without_vat,
                'image': variation.image
            })
        variations_df = pd.DataFrame(variations_data)
        print(f"Variations DataFrame shape: {variations_df.shape}")  # לוג לבדיקה
        
        # יצירת נתיב מלא לתיקיית הייצוא
        export_dir = os.path.join(app.root_path, 'static', 'exports')
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
            print(f"Created export directory: {export_dir}")  # לוג לבדיקה
        
        # שמירת הקבצים
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # שמירת קטגוריות
        categories_path = os.path.join(export_dir, f'categories_{timestamp}.csv')
        categories_df.to_csv(categories_path, index=False, encoding='utf-8-sig')
        print(f"Saved categories to {categories_path}")  # לוג לבדיקה
        
        # שמירת מוצרים
        products_path = os.path.join(export_dir, f'products_{timestamp}.csv')
        products_df.to_csv(products_path, index=False, encoding='utf-8-sig')
        print(f"Saved products to {products_path}")  # לוג לבדיקה
        
        # שמירת וריאציות
        variations_path = os.path.join(export_dir, f'variations_{timestamp}.csv')
        variations_df.to_csv(variations_path, index=False, encoding='utf-8-sig')
        print(f"Saved variations to {variations_path}")  # לוג לבדיקה
        
        # יצירת קובץ ZIP
        zip_path = os.path.join(export_dir, f'export_{timestamp}.zip')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(categories_path, f'categories_{timestamp}.csv')
            zipf.write(products_path, f'products_{timestamp}.csv')
            zipf.write(variations_path, f'variations_{timestamp}.csv')
        
        # מחיקת קבצי ה-CSV הבודדים
        os.remove(categories_path)
        os.remove(products_path)
        os.remove(variations_path)
        
        # החזרת קובץ ה-ZIP למשתמש
        return send_from_directory(
            export_dir,
            f'export_{timestamp}.zip',
            as_attachment=True,
            download_name=f'export_{timestamp}.zip'
        )
        
    except Exception as e:
        print(f"Error in export_all: {str(e)}")  # לוג שגיאה
        return jsonify({'success': False, 'message': f'אירעה שגיאה בייצוא: {str(e)}'})

@app.route('/import-all', methods=['POST'])
def import_all():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    try:
        # בדיקה אם יש קבצים שהועלו
        if 'categories' not in request.files and 'products' not in request.files and 'variations' not in request.files:
            return jsonify({'success': False, 'message': 'לא נבחרו קבצים לייבוא'})
        
        # ייבוא קטגוריות אם קיים
        if 'categories' in request.files and request.files['categories'].filename:
            categories_file = request.files['categories']
            if categories_file.filename.endswith('.csv'):
                categories_df = pd.read_csv(categories_file)
                print(f"Found {len(categories_df)} categories to import")
                
                # מחיקת קטגוריות קיימות
                Category.query.delete()
                
                # ייבוא קטגוריות חדשות
                for _, row in categories_df.iterrows():
                    category = Category(
                        name=row['name'],
                        image=row.get('image', None)  # שימוש ב-get עם ברירת מחדל
                    )
                    db.session.add(category)
                db.session.commit()
                print("Categories imported successfully")
        
        # ייבוא מוצרים אם קיים
        if 'products' in request.files and request.files['products'].filename:
            products_file = request.files['products']
            if products_file.filename.endswith('.csv'):
                products_df = pd.read_csv(products_file)
                print(f"Found {len(products_df)} products to import")
                
                # מחיקת מוצרים קיימים
                Product.query.delete()
                
                # ייבוא מוצרים חדשים
                for _, row in products_df.iterrows():
                    # חישוב מחיר ללא מע"מ
                    price_with_vat = float(row['price_with_vat'])
                    price_without_vat = price_with_vat / 1.18
                    
                    product = Product(
                        name=row['name'],
                        price_with_vat=price_with_vat,
                        price_without_vat=price_without_vat,
                        image=row.get('image', None),  # שימוש ב-get עם ברירת מחדל
                        category_id=row.get('category_id', None)  # שימוש ב-get עם ברירת מחדל
                    )
                    db.session.add(product)
                db.session.commit()
                print("Products imported successfully")
        
        # ייבוא וריאציות אם קיים
        if 'variations' in request.files and request.files['variations'].filename:
            variations_file = request.files['variations']
            if variations_file.filename.endswith('.csv'):
                variations_df = pd.read_csv(variations_file)
                print(f"Found {len(variations_df)} variations to import")
                
                # מחיקת וריאציות קיימות
                ProductVariation.query.delete()
                
                # ייבוא וריאציות חדשות
                for _, row in variations_df.iterrows():
                    # חישוב מחיר ללא מע"מ
                    price_with_vat = float(row['price_with_vat'])
                    price_without_vat = price_with_vat / 1.18
                    
                    variation = ProductVariation(
                        product_id=row['product_id'],
                        name=row['name'],
                        price_with_vat=price_with_vat,
                        price_without_vat=price_without_vat,
                        image=row.get('image', None)  # שימוש ב-get עם ברירת מחדל
                    )
                    db.session.add(variation)
                db.session.commit()
                print("Variations imported successfully")
        
        return jsonify({'success': True, 'message': 'הנתונים יובאו בהצלחה'})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error in import_all: {str(e)}")
        return jsonify({'success': False, 'message': f'אירעה שגיאה בייבוא: {str(e)}'})

@app.route('/import-categories', methods=['POST'])
def import_categories():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'לא נבחר קובץ'})
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'message': 'לא נבחר קובץ'})
    
    if not file.filename.endswith('.csv'):
        return jsonify({'success': False, 'message': 'נא להעלות קובץ CSV בלבד'})
    
    try:
        # קריאת הקובץ CSV
        df = pd.read_csv(file, encoding='utf-8-sig')
        required_columns = ['name']
        
        # בדיקת עמודות נדרשות
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return jsonify({
                'success': False, 
                'message': f'חסרות העמודות הבאות: {", ".join(missing_columns)}'
            })
        
        # ייבוא כל קטגוריה
        for _, row in df.iterrows():
            category = Category(
                name=row['name'],
                image=row.get('image', None)  # שימוש ב-get עם ברירת מחדל
            )
            db.session.add(category)
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'הקטגוריות יובאו בהצלחה'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'אירעה שגיאה בייבוא: {str(e)}'})

@app.route('/upload-logo', methods=['POST'])
def upload_logo():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'נדרשת התחברות'})
    
    if 'logo' not in request.files:
        return jsonify({'success': False, 'message': 'לא נבחר קובץ'})
    
    file = request.files['logo']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'לא נבחר קובץ'})
    
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': 'סוג הקובץ לא נתמך'})
    
    try:
        # וידוא שתיקיית ההעלאות קיימת
        if not os.path.exists(app.config['UPLOAD_FOLDER']):
            os.makedirs(app.config['UPLOAD_FOLDER'])
        
        # שמירת הקובץ בשם קבוע
        filename = 'logo.png'
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        return jsonify({'success': True, 'message': 'הלוגו הועלה בהצלחה'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'אירעה שגיאה בהעלאת הלוגו: {str(e)}'})

if __name__ == '__main__':
    app.run(debug=True) 