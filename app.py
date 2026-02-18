from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from supabase import create_client, Client
import bcrypt
import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import random
import string

app = Flask(__name__)

# Load .env file FIRST before anything else
from dotenv import load_dotenv
load_dotenv()

app.secret_key = os.getenv('SECRET_KEY', 'natts-digital-secret-2026')

# ============================================================
# SUPABASE
# ============================================================
supabase: Client = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_KEY')
)

# ============================================================
# HELPERS
# ============================================================
def get_stock_price(symbol):
    """
    Fetch stock price supporting both US and Australian markets.
    Auto-adds .AX suffix for Australian stocks.
    """
    try:
        import yfinance as yf
        
        # Try original symbol first (works for US stocks)
        ticker = yf.Ticker(symbol)
        data = ticker.history(period='1d')
        
        # If no data, try adding .AX for Australian stocks
        if data.empty and not symbol.endswith('.AX'):
            ticker = yf.Ticker(symbol + '.AX')
            data = ticker.history(period='1d')
        
        if not data.empty:
            price = float(data['Close'].iloc[-1])
            prev  = float(data['Open'].iloc[-1])
            change_pct = ((price - prev) / prev) * 100
            return price, change_pct
        
        return None, None
    except:
        return None, None

def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())

def send_email(to, subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = os.getenv('EMAIL_SENDER')
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP(os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
                              int(os.getenv('SMTP_PORT', 587)))
        server.starttls()
        server.login(os.getenv('EMAIL_SENDER'), os.getenv('EMAIL_PASSWORD'))
        server.sendmail(os.getenv('EMAIL_SENDER'), to, msg.as_string())
        server.quit()
        return True
    except:
        return False

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ============================================================
# AUTH ROUTES
# ============================================================
@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        try:
            result = supabase.table('users').select('*').execute()
            for user in result.data:
                if user['username'].lower() == username.lower():
                    if verify_password(password, user['password_hash']):
                        session['username'] = user['username']
                        session['name'] = user['name']
                        session['premium'] = user.get('premium', False)
                        session['trial_ends'] = user.get('trial_ends', '')
                        return redirect(url_for('dashboard'))
            error = "Invalid username or password"
        except Exception as e:
            error = f"Login error: {str(e)}"
    return render_template('login.html', error=error)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None
    success = None
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        email    = request.form.get('email', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')
        if not all([name, email, username, password]):
            error = "Please fill all fields"
        elif password != confirm:
            error = "Passwords don't match"
        elif len(password) < 6:
            error = "Password must be 6+ characters"
        else:
            try:
                trial_ends = (datetime.now() + timedelta(days=21)).isoformat()
                supabase.table('users').insert({
                    'username': username,
                    'password_hash': hash_password(password),
                    'email': email,
                    'name': name,
                    'trial_ends': trial_ends,
                    'premium': False
                }).execute()
                supabase.table('user_settings').insert({
                    'username': username,
                    'email': email,
                    'email_enabled': False,
                    'telegram_enabled': False,
                    'notification_method': 'both'
                }).execute()
                success = "Account created! Please login."
            except Exception as e:
                error = f"Error: {str(e)}"
    return render_template('signup.html', error=error, success=success)

@app.route('/forgot', methods=['GET', 'POST'])
def forgot():
    error = None
    success = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip()
        try:
            result = supabase.table('users').select('*').execute()
            found = None
            for u in result.data:
                if u['username'].lower() == username.lower() and u['email'].lower() == email.lower():
                    found = u
                    break
            if not found:
                error = "No account found with that username and email"
            else:
                temp_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                supabase.table('users').update(
                    {'password_hash': hash_password(temp_pass)}
                ).eq('username', found['username']).execute()
                
                # Try to send email
                email_sent = send_email(email, "Stock Alerts Pro - Password Reset",
                    f"Hi {found['name']},\n\nYour temporary password: {temp_pass}\n\nPlease login and change it in Settings.\n\nNatts Digital")
                
                if email_sent:
                    success = f"Temporary password sent to {email}"
                else:
                    # Email failed but password was changed - show temp password
                    success = f"Email failed to send. Your temporary password is: {temp_pass}"
        except Exception as e:
            error = f"Error: {str(e)}"
    return render_template('forgot.html', error=error, success=success)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ============================================================
# DASHBOARD
# ============================================================
@app.route('/dashboard')
@login_required
def dashboard():
    username = session['username']
    alerts = supabase.table('alerts').select('*').eq('username', username).execute().data

    alert_list = []
    for a in alerts:
        price, change_pct = get_stock_price(a['symbol'])
        status = 'waiting'
        if price:
            if a['type'] == 'above' and price >= a['target']:
                status = 'triggered'
            elif a['type'] == 'below' and price <= a['target']:
                status = 'triggered'
        alert_list.append({
            **a,
            'price': f"${price:.2f}" if price else "—",
            'change_pct': f"{change_pct:+.2f}%" if change_pct else "",
            'change_up': change_pct >= 0 if change_pct else True,
            'status': status,
            'news_url': f"https://finance.yahoo.com/quote/{a['symbol']}/news"
        })

    # Account status
    trial_ends = session.get('trial_ends', '')
    days_left = 0
    if trial_ends:
        try:
            te = datetime.fromisoformat(trial_ends.replace('Z',''))
            days_left = max(0, (te - datetime.now()).days)
        except:
            pass

    return render_template('dashboard.html',
        alerts=alert_list,
        username=username,
        name=session.get('name', username),
        premium=session.get('premium', False),
        days_left=days_left,
        alert_count=len(alerts),
        alert_limit=10
    )

# ============================================================
# ADD ALERT
# ============================================================
@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_alert():
    error = None
    success = None
    price_preview = None
    if request.method == 'POST':
        symbol      = request.form.get('symbol', '').upper().strip()
        target      = request.form.get('target', '')
        alert_type  = request.form.get('alert_type', 'above')
        if not symbol or not target:
            error = "Please fill all fields"
        else:
            try:
                target = float(target)
                supabase.table('alerts').insert({
                    'username': session['username'],
                    'symbol': symbol,
                    'target': target,
                    'type': alert_type,
                    'enabled': True
                }).execute()
                return redirect(url_for('dashboard'))
            except Exception as e:
                error = f"Error: {str(e)}"
    return render_template('add_alert.html', error=error, success=success)

@app.route('/price/<symbol>')
@login_required
def get_price(symbol):
    price, change = get_stock_price(symbol.upper())
    return jsonify({'price': price, 'change': change})

# ============================================================
# EDIT ALERT
# ============================================================
@app.route('/edit/<alert_id>', methods=['GET', 'POST'])
@login_required
def edit_alert(alert_id):
    if request.method == 'POST':
        target     = float(request.form.get('target'))
        alert_type = request.form.get('alert_type')
        supabase.table('alerts').update({
            'target': target, 'type': alert_type
        }).eq('id', alert_id).execute()
        return redirect(url_for('dashboard'))
    alert = supabase.table('alerts').select('*').eq('id', alert_id).execute().data
    if not alert:
        return redirect(url_for('dashboard'))
    return render_template('edit_alert.html', alert=alert[0])

# ============================================================
# DELETE ALERT
# ============================================================
@app.route('/delete/<alert_id>', methods=['POST'])
@login_required
def delete_alert(alert_id):
    supabase.table('alerts').delete().eq('id', alert_id).execute()
    return redirect(url_for('dashboard'))

# ============================================================
# SETTINGS
# ============================================================
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    username = session['username']
    error = None
    success = None
    s = supabase.table('user_settings').select('*').eq('username', username).execute().data
    user_settings = s[0] if s else {}

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'save_notifications':
            supabase.table('user_settings').update({
                'email': request.form.get('email', ''),
                'email_enabled': 'email_enabled' in request.form,
                'telegram_chat_id': request.form.get('telegram_chat_id', ''),
                'telegram_enabled': 'telegram_enabled' in request.form,
                'notification_method': request.form.get('notification_method', 'both')
            }).eq('username', username).execute()
            success = "Settings saved!"

        elif action == 'change_password':
            curr = request.form.get('current_password')
            new  = request.form.get('new_password')
            conf = request.form.get('confirm_password')
            if new != conf:
                error = "New passwords don't match"
            elif len(new) < 6:
                error = "Password must be 6+ characters"
            else:
                result = supabase.table('users').select('*').eq('username', username).execute()
                if result.data and verify_password(curr, result.data[0]['password_hash']):
                    supabase.table('users').update(
                        {'password_hash': hash_password(new)}
                    ).eq('username', username).execute()
                    success = "Password changed!"
                else:
                    error = "Current password incorrect"

        s = supabase.table('user_settings').select('*').eq('username', username).execute().data
        user_settings = s[0] if s else {}

    return render_template('settings.html',
        username=username,
        name=session.get('name', username),
        settings=user_settings,
        error=error,
        success=success
    )

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8502))
    app.run(host='0.0.0.0', port=port, debug=False)
