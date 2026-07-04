# Import Flask and required tools
from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_login import login_required, login_user, logout_user

# Import database functions
from database import init_db, save_trade, get_all_trades, get_statistics

# Import news functions
from news import get_forex_news, get_trade_verdict

# Import authentication
from auth import login_manager, check_credentials, goat_user

# Import os for environment variables
import os
from dotenv import load_dotenv

load_dotenv()

# Create Flask app
app = Flask(__name__)

# Secret key required for session management
# Used to encrypt the login session cookie
app.secret_key = os.getenv('GOAT_SECRET_KEY', 'goat-trading-journal-secret-2026')

# Initialize login manager
login_manager.init_app(app)

# Initialize database
init_db()

# ── AUTHENTICATION ROUTES ──

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if check_credentials(username, password):
            login_user(goat_user)
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error='Invalid username or password')

    return render_template('login.html', error=None)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ── MAIN ROUTES ──

@app.route('/')
@login_required
def home():
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/news')
@login_required
def news():
    articles = get_forex_news()
    verdict = get_trade_verdict(articles)
    return render_template('news.html', articles=articles, verdict=verdict)

# ── API ROUTES ──

@app.route('/trades', methods=['POST'])
@login_required
def add_trade():
    data = request.get_json()

    required_fields = ['pair', 'session', 'entry', 'stop_loss',
                       'take_profit', 'result', 'r_multiple', 'account', 'date']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    pair = data['pair']
    session = data['session']
    entry = data['entry']
    stop_loss = data['stop_loss']
    take_profit = data['take_profit']
    result = data['result']
    r_multiple = data['r_multiple']
    account = data['account']
    date = data['date']
    notes = data.get('notes', '')

    save_trade(pair, session, entry, stop_loss, take_profit,
               result, r_multiple, account, date, notes)

    return jsonify({'message': 'Trade saved successfully'}), 201

@app.route('/trades', methods=['GET'])
@login_required
def get_trades():
    trades = get_all_trades()
    return jsonify(trades), 200

@app.route('/stats', methods=['GET'])
@login_required
def get_stats():
    stats = get_statistics()
    return jsonify(stats), 200

# ── RUN ──
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)