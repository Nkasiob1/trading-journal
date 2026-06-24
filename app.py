# Import the Flask class from the flask library we installed
from flask import Flask

# Import the init_db function from our database file
from database import init_db

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

# Only run the app if this file is being run directly
if __name__ == '__main__':
    # Start the Flask web server with debug=True
    app.run(debug=True)