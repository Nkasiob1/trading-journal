from flask import Flask
# Create an instance of the Flask app and assign it to a variable called app
# __name__ tells Flask where to look for files related to this app
app = Flask(__name__)
# This is a decorator — it tells Flask that when someone visits '/' (the homepage)
# it should run the function directly below it
@app.route('/')
# This is the function that runs when someone visits the homepage
def home():
     # This is what gets sent back to the browser when the homepage is visited
     return 'GOAT Trading Journal is running'
# This means: only run the app if this file is being run directly
# not if it's being imported by another file
if __name__=='__main__':
      # Start the Flask web server with debug=True
    # debug=True means the server restarts automatically when you save changes
    # and shows detailed error messages in the browser
    app.run(debug=True)