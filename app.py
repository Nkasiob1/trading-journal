# Import the Flask class from the flask library we installed
from flask import Flask, request, jsonify

# Import the init_db function from our database file
from database import init_db, save_trade, get_all_trades, get_statistics

# Create an instance of the Flask app
# __name__ tells Flask where to look for files related to this app
app = Flask(__name__)

# Initialize the database when the app starts
init_db()

# This decorator tells Flask that when someone visits '/' run the function below
@app.route('/')
def home():
    # This is what gets sent back to the browser when the homepage is visited
    return 'GOAT Trading Journal is running'

# POST route — accepts trade data and saves it to the database    
@app.route('/trades', methods=['POST'])
def add_trade():
    # Get the JSON data sent in the request body
    data = request.get_json()

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

    # Save the trades to database 
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

# Only run the app if this file is being run directly
if __name__ == '__main__':
    # Start the Flask web server with debug=True
    app.run(debug=True)