# Import the Flask class from the flask library we installed
from flask import Flask, request, jsonify, render_template 

# Import the init_db function from our database file
from database import init_db, save_trade, get_all_trades, get_statistics

# Import the news function
from news import get_forex_news

# Create an instance of the Flask app
# __name__ tells Flask where to look for files related to this app
app = Flask(__name__)

# Initialize the database when the app starts
init_db()

# This decorator tells Flask that when someone visits '/' run the function below
@app.route('/')
def home():
    # This is what gets sent back to the browser when the homepage is visited
    return render_template('index.html')

@app.route('/trades', methods=['POST'])
def add_trade():
    # Get the JSON data sent in the request body
    data = request.get_json()

    # Validate that all required fields are present
    required_fields = ['pair', 'session', 'entry', 'stop_loss', 'take_profit', 'result', 'r_multiple', 'account', 'date']
    for field in required_fields:
        if field not in data:
            # Return a 400 Bad Request response if a field is missing
            return jsonify({'error': f'Missing required field: {field}'}), 400

    # Extract each field from the data
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

    # Save the trade to the database
    save_trade(pair, session, entry, stop_loss, take_profit, result, r_multiple, account, date, notes)

    # Return a success response
    return jsonify({'message': 'Trade saved successfully'}), 201

# Get route - retrieves all trade from the database 
@app.route('/trades', methods=['GET'])
def get_trades():
    # get all trades from the database
    trades = get_all_trades()

    # Return the tades as JSON
    return jsonify(trades), 200

# GET route — returns trading statistics
@app.route('/stats', methods=['GET'])
def get_stats():
    # Get statistics from the database
    stats = get_statistics()
    
    # Return statistics as JSON
    return jsonify(stats), 200

# GET route — serves the dashboard page
@app.route('/dashboard')
def dashboard():
    # Serve the dashboard HTML page
    return render_template('dashboard.html')

# GET route — serves the news feed page
@app.route('/news')
def news():
    # Fetch today's forex news
    articles = get_forex_news()
    
    # Serve the news page with the articles
    return render_template('news.html', articles=articles)

# Only run the app if this file is being run directly
if __name__ == '__main__':
    # Start the Flask web server with debug=True
    app.run(debug=True)