from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from supabase import create_client, Client
import bcrypt
import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import stripe
from datetime import datetime, timedelta
import random
import string

app = Flask(__name__)

# Load .env file FIRST before anything else
from dotenv import load_dotenv
load_dotenv()

app.secret_key = os.getenv('SECRET_KEY', 'natts-digital-secret-2026')

# Stripe configuration
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')
STRIPE_PRICE_MONTHLY = os.getenv('STRIPE_PRICE_MONTHLY', 'price_1T2isyEX5QghswoUgNNcfJCN')
STRIPE_PRICE_ANNUAL = os.getenv('STRIPE_PRICE_ANNUAL', 'price_1T2iusEX5QghswoUFfYVYedR')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')

# ============================================================
# SUPABASE
# ============================================================
supabase: Client = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_KEY')
)

# ============================================================
# BACKGROUND ALERT CHECKER WITH CACHING
# ============================================================
from apscheduler.schedulers.background import BackgroundScheduler
from collections import defaultdict

# Price cache: {symbol: (price, timestamp)}
_price_cache = {}
CACHE_DURATION = 60  # 1 minute cache

def get_cached_price(symbol):
    """Get price from cache if fresh, otherwise fetch new"""
    import time
    
    # Check cache
    if symbol in _price_cache:
        cached_price, cached_time = _price_cache[symbol]
        if time.time() - cached_time < CACHE_DURATION:
            print(f"Cache hit for {symbol}: ${cached_price}")
            return cached_price
    
    # Cache miss - fetch new price
    price, _ = get_stock_price(symbol)
    if price:
        _price_cache[symbol] = (price, time.time())
        print(f"Fetched fresh price for {symbol}: ${price}")
    return price

def check_alerts_job():
    """Background job to check all alerts with batching and caching"""
    try:
        # Check if major markets are open (US or Australia)
        from datetime import datetime
        import pytz
        
        now_utc = datetime.now(pytz.UTC)
        now_ny = now_utc.astimezone(pytz.timezone('America/New_York'))
        now_sydney = now_utc.astimezone(pytz.timezone('Australia/Sydney'))
        
        # US market hours: 9:30 AM - 4:00 PM ET, Mon-Fri
        us_open = (now_ny.weekday() < 5 and 
                   9 <= now_ny.hour < 16 and 
                   not (now_ny.hour == 9 and now_ny.minute < 30))
        
        # ASX hours: 10:00 AM - 4:00 PM AEDT, Mon-Fri
        asx_open = (now_sydney.weekday() < 5 and 
                    10 <= now_sydney.hour < 16)
        
        if not us_open and not asx_open:
            print(f"Markets closed - skipping check (NY: {now_ny.strftime('%H:%M %a')}, Sydney: {now_sydney.strftime('%H:%M %a')})")
            return
        
        # Get all enabled alerts
        all_alerts = supabase.table('alerts').select('*').eq('enabled', True).execute().data
        
        if not all_alerts:
            return
        
        # Group alerts by symbol for batch processing
        alerts_by_symbol = defaultdict(list)
        for alert in all_alerts:
            alerts_by_symbol[alert['symbol']].append(alert)
        
        print(f"Checking {len(all_alerts)} alerts across {len(alerts_by_symbol)} symbols")
        
        # Process each symbol once (batch processing)
        for symbol, symbol_alerts in alerts_by_symbol.items():
            # Get price once for all alerts of this symbol (uses cache if available)
            price = get_cached_price(symbol)
            if not price:
                continue
            
            # Check all alerts for this symbol
            for alert in symbol_alerts:
                triggered = False
                if alert['type'] == 'above' and price >= alert['target']:
                    triggered = True
                elif alert['type'] == 'below' and price <= alert['target']:
                    triggered = True
                
                if triggered:
                # Get user settings
                username = alert['username']
                settings_result = supabase.table('user_settings').select('*').eq('username', username).execute()
                user_result = supabase.table('users').select('*').eq('username', username).execute()
                
                if not settings_result.data or not user_result.data:
                    continue
                
                settings = settings_result.data[0]
                user = user_result.data[0]
                
                # Send Telegram notification
                if settings.get('telegram_enabled'):
                    chat_id = settings.get('telegram_chat_id') or os.getenv('TELEGRAM_CHAT_ID')
                    if chat_id:
                        direction = "🔼 above" if alert['type'] == 'above' else "🔽 below"
                        msg = f"""🚀 Alert Triggered!

Hi {user['name']},

{alert['symbol']} crossed your target!

💰 Current Price: ${price:.2f}
🎯 Your Target: ${alert['target']:.2f} {direction}

Manage alerts: https://stock-alerts-flask.onrender.com

Natts Digital"""
                        send_telegram(msg, chat_id)
                
                # Disable alert after triggering (prevents spam)
                supabase.table('alerts').update({'enabled': False}).eq('id', alert['id']).execute()
                
    except Exception as e:
        print(f"Alert checker error: {str(e)}")

def send_telegram(message, chat_id):
    """Send Telegram notification"""
    try:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not bot_token:
            return False
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(url, json={'chat_id': chat_id, 'text': message})
        return True
    except:
        return False

# Start background scheduler
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(func=check_alerts_job, trigger="interval", minutes=5)

# Add self-ping to prevent Render free tier from sleeping
def keep_alive():
    """Ping self to prevent Render spin-down"""
    try:
        app_url = os.getenv('APP_URL', 'https://stock-alerts-flask.onrender.com')
        requests.get(app_url, timeout=5)
        print("Keep-alive ping sent")
    except Exception as e:
        print(f"Keep-alive error: {str(e)}")

scheduler.add_job(func=keep_alive, trigger="interval", minutes=10)

try:
    scheduler.start()
    print("Background scheduler started successfully")
except Exception as e:
    print(f"Scheduler start error: {str(e)}")

# Shutdown scheduler on app exit
import atexit
atexit.register(lambda: scheduler.shutdown())

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

def get_stock_sparkline(symbol):
    """Get 1-month historical prices for sparkline chart (faster)"""
    try:
        import yfinance as yf
        
        # Try original symbol first
        ticker = yf.Ticker(symbol)
        data = ticker.history(period='1mo')  # Changed from 3mo to 1mo for speed
        
        # If no data, try .AX suffix
        if data.empty and not symbol.endswith('.AX'):
            ticker = yf.Ticker(symbol + '.AX')
            data = ticker.history(period='1mo')
        
        if not data.empty and len(data) > 0:
            # Get closing prices as list (max 20 points for speed)
            prices = data['Close'].tolist()
            # Sample every nth point to get ~20 data points
            step = max(1, len(prices) // 20)
            sampled = [prices[i] for i in range(0, len(prices), step)]
            return sampled if sampled else []
        
        return []
    except Exception as e:
        print(f"Sparkline error for {symbol}: {str(e)}")
        return []

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
        
        # Add timeout to prevent hanging
        server = smtplib.SMTP(os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
                              int(os.getenv('SMTP_PORT', 587)),
                              timeout=10)
        server.starttls()
        server.login(os.getenv('EMAIL_SENDER'), os.getenv('EMAIL_PASSWORD'))
        server.sendmail(os.getenv('EMAIL_SENDER'), to, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Email error: {str(e)}")
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
@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'message': 'App is running'})

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
            # Check for duplicate username or email
            try:
                existing = supabase.table('users').select('username, email').execute().data
                usernames = [u['username'].lower() for u in existing]
                emails = [u['email'].lower() for u in existing]
                
                if username.lower() in usernames:
                    error = "Username already taken. Please choose a different one."
                elif email.lower() in emails:
                    error = "Email already registered. Please use a different email or try forgot password."
                else:
                    # Create new user
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
                        'notification_method': 'telegram',
                        'setup_complete': False
                    }).execute()
                    success = """🎉 Welcome to Stock Alerts Pro!

Your account is ready! Here's what to do next:

1️⃣ Login below with your username and password
2️⃣ Go to Settings ⚙️ (top right menu)
3️⃣ Add your Telegram Chat ID (search @userinfobot on Telegram to get it)
4️⃣ Enable notifications and click Test
5️⃣ Start adding stock alerts! 📊

You have 21 days free trial to explore all features."""
            except Exception as e:
                error = f"Error: {str(e)}"
    return render_template('signup.html', error=error, success=success)

@app.route('/forgot', methods=['GET', 'POST'])
def forgot():
    error = None
    success = None
    if request.method == 'POST':
        action = request.form.get('action', 'password')
        email = request.form.get('email', '').strip()
        
        if action == 'username':
            # Forgot Username - only need email
            try:
                result = supabase.table('users').select('*').execute()
                found = None
                for u in result.data:
                    if u['email'].lower() == email.lower():
                        found = u
                        break
                
                if not found:
                    error = "No account found with that email address"
                else:
                    # Try to send via Telegram
                    settings = supabase.table('user_settings').select('*').eq('username', found['username']).execute()
                    telegram_sent = False
                    
                    if settings.data:
                        chat_id = settings.data[0].get('telegram_chat_id')
                        if chat_id:
                            msg = f"""📋 Username Recovery - Stock Alerts Pro

Hi {found['name']},

Your username is: {found['username']}

Login at: https://stock-alerts-flask.onrender.com

Natts Digital"""
                            telegram_sent = send_telegram(msg, chat_id)
                    
                    if telegram_sent:
                        success = f"✅ Your username has been sent to your Telegram!"
                    else:
                        success = f"""✅ Username found!

Your username is: <strong style="font-size:18px;background:#f0f0f0;padding:8px 12px;border-radius:4px;display:inline-block;margin:8px 0;">{found['username']}</strong>

You can now login below."""
            except Exception as e:
                error = f"Error: {str(e)}"
        
        else:
            # Forgot Password - need username and email
            username = request.form.get('username', '').strip()
            try:
                result = supabase.table('users').select('*').execute()
                found = None
                for u in result.data:
                    if u['username'].lower() == username.lower() and u['email'].lower() == email.lower():
                        found = u
                        break
                if not found:
                    error = "No account found with that username and email combination"
                else:
                    # Generate temporary password
                    temp_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                    supabase.table('users').update(
                        {'password_hash': hash_password(temp_pass)}
                    ).eq('username', found['username']).execute()
                    
                    # Try to send via Telegram
                    settings = supabase.table('user_settings').select('*').eq('username', found['username']).execute()
                    telegram_sent = False
                    
                    if settings.data:
                        chat_id = settings.data[0].get('telegram_chat_id')
                        if chat_id:
                            msg = f"""🔐 Password Reset - Stock Alerts Pro

Hi {found['name']},

Your temporary password is: {temp_pass}

Please login and change it in Settings immediately.

Login at: https://stock-alerts-flask.onrender.com

Natts Digital"""
                            telegram_sent = send_telegram(msg, chat_id)
                    
                    if telegram_sent:
                        success = f"✅ Temporary password sent to your Telegram! Check your messages."
                    else:
                        success = f"""⚠️ Your password has been reset!

Your temporary password is: <strong style="font-size:18px;background:#f0f0f0;padding:8px 12px;border-radius:4px;display:inline-block;margin:8px 0;">{temp_pass}</strong>

Please copy this, login, and change it in Settings immediately."""
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
        sparkline_data = get_stock_sparkline(a['symbol'])
        
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
            'news_url': f"https://finance.yahoo.com/quote/{a['symbol']}/news",
            'chart_url': f"https://finance.yahoo.com/quote/{a['symbol']}/chart",
            'sparkline': sparkline_data
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
    
    # Check if user needs to setup Telegram
    settings = supabase.table('user_settings').select('*').eq('username', username).execute().data
    needs_setup = False
    if settings:
        s = settings[0]
        # User needs setup if Telegram is not enabled or no Chat ID
        needs_setup = not s.get('telegram_enabled') or not s.get('telegram_chat_id')

    return render_template('dashboard.html',
        alerts=alert_list,
        username=username,
        name=session.get('name', username),
        premium=session.get('premium', False),
        days_left=days_left,
        alert_count=len(alerts),
        alert_limit=10,
        needs_setup=needs_setup
    )

# ============================================================
# ADD ALERT
# ============================================================
@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_alert():
    error = None
    success = None
    username = session['username']
    
    # Check alert limit
    alerts = supabase.table('alerts').select('*').eq('username', username).execute().data
    alert_count = len(alerts)
    alert_limit = 10  # Free tier limit
    
    # Check if premium
    user = supabase.table('users').select('*').eq('username', username).execute().data
    is_premium = user[0]['premium'] if user else False
    
    if request.method == 'POST':
        # Enforce limit for non-premium users
        if not is_premium and alert_count >= alert_limit:
            error = f"⚠️ Free trial limit reached ({alert_limit} alerts). Upgrade to Premium for unlimited alerts!"
        elif not request.form.get('symbol') or not request.form.get('target'):
            error = "Please fill all fields"
        else:
            try:
                symbol = request.form.get('symbol', '').upper().strip()
                target = float(request.form.get('target', ''))
                alert_type = request.form.get('alert_type', 'above')
                
                supabase.table('alerts').insert({
                    'username': username,
                    'symbol': symbol,
                    'target': target,
                    'type': alert_type,
                    'enabled': True
                }).execute()
                return redirect(url_for('dashboard'))
            except Exception as e:
                error = f"Error: {str(e)}"
    
    # Pass limit info to template
    at_limit = not is_premium and alert_count >= alert_limit
    return render_template('add_alert.html', 
                          error=error, 
                          success=success,
                          alert_count=alert_count,
                          alert_limit=alert_limit,
                          at_limit=at_limit,
                          is_premium=is_premium)

@app.route('/price/<symbol>')
@login_required
def get_price(symbol):
    """Get price and verify stock across markets with database-backed company name cache"""
    import yfinance as yf
    symbol = symbol.upper()
    results = []
    
    # Check US market
    try:
        ticker_us = yf.Ticker(symbol)
        data_us = ticker_us.history(period='1d', timeout=10)
        if not data_us.empty:
            price_us = float(data_us['Close'].iloc[-1])
            
            # Check database cache first
            cached = supabase.table('stock_info').select('*').eq('symbol', symbol).execute()
            
            if cached.data:
                # Use cached data
                stock_name = cached.data[0]['company_name']
                exchange = cached.data[0]['exchange']
                currency = cached.data[0]['currency']
                print(f"US stock {symbol}: using cached name from DB={stock_name}")
            else:
                # Not in cache, try to fetch from yfinance
                stock_name = symbol
                exchange = 'US Market'
                currency = 'USD'
                
                try:
                    info_us = ticker_us.info
                    if info_us:
                        fetched_name = (info_us.get('longName') or 
                                       info_us.get('shortName') or 
                                       symbol)
                        if fetched_name != symbol:
                            stock_name = fetched_name
                            exchange = info_us.get('exchange', 'US Market')
                            currency = info_us.get('currency', 'USD')
                            
                            # Save to database cache
                            try:
                                supabase.table('stock_info').insert({
                                    'symbol': symbol,
                                    'company_name': stock_name,
                                    'exchange': exchange,
                                    'currency': currency,
                                    'market': 'US'
                                }).execute()
                                print(f"US stock {symbol}: cached to DB name={stock_name}")
                            except:
                                pass  # Ignore duplicate key errors
                except Exception as e:
                    print(f"US info error for {symbol}: {str(e)}")
            
            results.append({
                'symbol': symbol,
                'name': stock_name,
                'exchange': exchange,
                'price': price_us,
                'currency': currency,
                'market': 'US'
            })
    except Exception as e:
        print(f"US market search error for {symbol}: {str(e)}")
    
    # Check ASX market
    try:
        ticker_ax = yf.Ticker(symbol + '.AX')
        data_ax = ticker_ax.history(period='1d', timeout=10)
        if not data_ax.empty:
            price_ax = float(data_ax['Close'].iloc[-1])
            
            # Check database cache first
            cached = supabase.table('stock_info').select('*').eq('symbol', symbol + '.AX').execute()
            
            if cached.data:
                stock_name = cached.data[0]['company_name']
                currency = cached.data[0]['currency']
                print(f"ASX stock {symbol}.AX: using cached name from DB={stock_name}")
            else:
                stock_name = symbol
                currency = 'AUD'
                
                try:
                    info_ax = ticker_ax.info
                    if info_ax:
                        fetched_name = (info_ax.get('longName') or 
                                       info_ax.get('shortName') or 
                                       symbol)
                        if fetched_name != symbol:
                            stock_name = fetched_name
                            currency = info_ax.get('currency', 'AUD')
                            
                            # Save to database cache
                            try:
                                supabase.table('stock_info').insert({
                                    'symbol': symbol + '.AX',
                                    'company_name': stock_name,
                                    'exchange': 'ASX',
                                    'currency': currency,
                                    'market': 'Australia'
                                }).execute()
                                print(f"ASX stock {symbol}.AX: cached to DB name={stock_name}")
                            except:
                                pass
                except Exception as e:
                    print(f"ASX info error for {symbol}: {str(e)}")
            
            results.append({
                'symbol': symbol + '.AX',
                'name': stock_name,
                'exchange': 'ASX',
                'price': price_ax,
                'currency': currency,
                'market': 'Australia'
            })
    except Exception as e:
        print(f"ASX market search error for {symbol}: {str(e)}")
    
    return jsonify({'results': results})

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
# QUICK UPDATE ALERT (for inline editing)
# ============================================================
@app.route('/api/update_alert/<alert_id>', methods=['POST'])
@login_required
def quick_update_alert(alert_id):
    """Quick update endpoint for inline editing"""
    try:
        data = request.get_json()
        target = data.get('target')
        alert_type = data.get('type')
        
        # Validate
        if target is not None:
            target = float(target)
            if target <= 0:
                return jsonify({'success': False, 'error': 'Target must be positive'}), 400
        
        # Build update dict
        updates = {}
        if target is not None:
            updates['target'] = target
        if alert_type in ['above', 'below']:
            updates['type'] = alert_type
        
        if updates:
            supabase.table('alerts').update(updates).eq('id', alert_id).execute()
            return jsonify({'success': True})
        
        return jsonify({'success': False, 'error': 'No valid updates'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# STRIPE SUBSCRIPTION
# ============================================================
@app.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    """Create Stripe checkout session for subscription"""
    try:
        plan = request.form.get('plan', 'monthly')
        price_id = STRIPE_PRICE_MONTHLY if plan == 'monthly' else STRIPE_PRICE_ANNUAL
        
        checkout_session = stripe.checkout.Session.create(
            customer_email=session.get('email'),
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + 'success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'settings?canceled=true',
            metadata={
                'username': session['username']
            }
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        print(f"Stripe checkout error: {str(e)}")
        return redirect(url_for('settings', error='payment'))

@app.route('/success')
@login_required
def success():
    """Payment success page"""
    return render_template('success.html', username=session.get('username'))

@app.route('/cancel-subscription', methods=['POST'])
@login_required
def cancel_subscription():
    """Cancel Stripe subscription but keep access until period end"""
    try:
        username = session['username']
        user = supabase.table('users').select('*').eq('username', username).execute().data
        
        if not user or not user[0].get('stripe_subscription_id'):
            return redirect(url_for('settings', error='No active subscription found'))
        
        subscription_id = user[0]['stripe_subscription_id']
        
        # Cancel at period end (user keeps access until then)
        stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True
        )
        
        # Update database to mark as canceling
        supabase.table('users').update({
            'subscription_cancel_at_period_end': True
        }).eq('username', username).execute()
        
        return redirect(url_for('settings', success='Subscription cancelled. You\'ll keep premium access until the end of your billing period.'))
        
    except Exception as e:
        print(f"Cancel subscription error: {str(e)}")
        return redirect(url_for('settings', error='Failed to cancel subscription'))

@app.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhook events"""
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError as e:
        return jsonify({'error': 'Invalid signature'}), 400
    
    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session_data = event['data']['object']
        username = session_data['metadata']['username']
        
        # Activate premium
        supabase.table('users').update({
            'premium': True,
            'stripe_customer_id': session_data.get('customer'),
            'stripe_subscription_id': session_data.get('subscription')
        }).eq('username', username).execute()
        
        print(f"✅ Premium activated for {username}")
    
    elif event['type'] == 'customer.subscription.deleted':
        # Subscription actually ended - remove premium access
        subscription = event['data']['object']
        
        # Deactivate premium
        supabase.table('users').update({
            'premium': False,
            'subscription_cancel_at_period_end': False,
            'stripe_subscription_id': None
        }).eq('stripe_subscription_id', subscription['id']).execute()
        
        print(f"❌ Premium ended for subscription {subscription['id']}")
    
    elif event['type'] == 'customer.subscription.updated':
        # Handle subscription updates (cancellation scheduled, reactivation, etc.)
        subscription = event['data']['object']
        
        supabase.table('users').update({
            'subscription_cancel_at_period_end': subscription.get('cancel_at_period_end', False)
        }).eq('stripe_subscription_id', subscription['id']).execute()
        
        print(f"🔄 Subscription updated: {subscription['id']}, cancel_at_period_end={subscription.get('cancel_at_period_end')}")
    
    return jsonify({'status': 'success'}), 200

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
                'telegram_chat_id': request.form.get('telegram_chat_id', ''),
                'telegram_enabled': 'telegram_enabled' in request.form,
                'notification_method': 'telegram'
            }).eq('username', username).execute()
            success = "Settings saved!"

        elif action == 'test_notification':
            user = supabase.table('users').select('*').eq('username', username).execute().data[0]
            
            # Test Telegram only
            if user_settings.get('telegram_enabled'):
                chat_id = user_settings.get('telegram_chat_id') or os.getenv('TELEGRAM_CHAT_ID')
                if chat_id:
                    sent = send_telegram(f"🧪 Test Alert\n\nHi {user['name']}!\n\nThis is a test from Stock Alerts Pro.\n\nIf you received this, your Telegram alerts are working perfectly! ✅", chat_id)
                    if sent:
                        success = f"✅ Test notification sent to Telegram Chat ID {chat_id}"
                    else:
                        error = "❌ Telegram failed - check TELEGRAM_BOT_TOKEN on Render"
                else:
                    error = "❌ No Telegram Chat ID configured. Enter it above and save first."
            else:
                error = "❌ Enable Telegram notifications first (check the box and save)"

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
    
    # Get premium status and cancellation info
    user = supabase.table('users').select('premium, subscription_cancel_at_period_end').eq('username', username).execute().data
    is_premium = user[0]['premium'] if user else False
    cancel_at_period_end = user[0].get('subscription_cancel_at_period_end', False) if user else False
    user_settings['premium'] = is_premium
    user_settings['subscription_cancel_at_period_end'] = cancel_at_period_end

    return render_template('settings.html',
        username=username,
        name=session.get('name', username),
        settings=user_settings,
        error=error,
        success=success
    )

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8502))
    print(f"Starting Flask app on port {port}...")
    try:
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        print(f"FATAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
