import sqlite3
# This function creates the database and the trades table if they don't exist yet
def init_db():
     # Connect to the database file — if it doesn't exist, SQLite creates it automatically
    conn = sqlite3.connect('goat.db')
     # Create a cursor — this is the tool we use to send SQL commands to the database
    cursor = conn.cursor()
    # Execute a SQL command to create the trades table
    # IF NOT EXISTS means it won't crash if the table already exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL,
            session TEXT NOT NULL,
            entry REAL NOT NULL,
            stop_loss REAL NOT NULL,
            take_profit REAL NOT NULL,
            result TEXT NOT NULL,
            r_multiple REAL,
            account TEXT NOT NULL,
            date TEXT NOT NULL,
            notes TEXT
        )
    ''')
     # Save the changes to the database
    conn.commit()
     # Close the connection — always close when done
    conn.close()

# This function saves a new trade to the database
def save_trade(pair, session, entry, stop_loss, take_profit, result, r_multiple, account, date, notes):
    # Connect to the database
    conn = sqlite3.connect('goat.db')

    #Create a cursor to send sql commands 
    cursor = conn.cursor()

    # Insert the trade data into the trades table
    # The ? marks are placeholders — SQLite fills them in safely to prevent SQL injection
    cursor.execute('''
        INSERT INTO trades (pair, session, entry, stop_loss, take_profit, result, r_multiple, account, date, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (pair, session, entry, stop_loss, take_profit, result, r_multiple, account, date, notes))
    # Save the changes
    conn.commit()

    #Close connection 
    conn.close()

# This function retrieves all trades from the database
def get_all_trades():
    # Connect to the database
    conn = sqlite3.connect('goat.db')    
      
    # Create a cursor
    cursor = conn.cursor()
    
    # Select all rows from the trades table
    cursor.execute('SELECT * FROM trades')
    
    # Fetch all results and store them
    trades = cursor.fetchall()
    
    # Close the connection
    conn.close()
    
    # Return the list of trades
    return trades
  