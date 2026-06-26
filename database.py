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
  
# This function calculates trading statistics from all logged trades
def get_statistics():
    # Connect to the database
    conn = sqlite3.connect('goat.db')
    
    # Create a cursor
    cursor = conn.cursor()
    
    # Get total number of trades
    cursor.execute('SELECT COUNT(*) FROM trades')
    total_trades = cursor.fetchone()[0]
    
    # Get number of winning trades
    cursor.execute("SELECT COUNT(*) FROM trades WHERE result = 'WIN'")
    total_wins = cursor.fetchone()[0]
    
    # Get number of losing trades
    cursor.execute("SELECT COUNT(*) FROM trades WHERE result = 'LOSS'")
    total_losses = cursor.fetchone()[0]
    
    # Get average R-multiple
    cursor.execute('SELECT AVG(r_multiple) FROM trades')
    avg_r = cursor.fetchone()[0]
    
    # Get total R gained or lost
    cursor.execute('SELECT SUM(r_multiple) FROM trades')
    total_r = cursor.fetchone()[0]
    
    # Get London session win rate
    cursor.execute("SELECT COUNT(*) FROM trades WHERE session = 'London'")
    london_trades = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM trades WHERE session = 'London' AND result = 'WIN'")
    london_wins = cursor.fetchone()[0]
    
    # Get New York session win rate
    cursor.execute("SELECT COUNT(*) FROM trades WHERE session = 'New York'")
    ny_trades = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM trades WHERE session = 'New York' AND result = 'WIN'")
    ny_wins = cursor.fetchone()[0]
    
    # Close the connection
    conn.close()
    
    # Calculate win rate safely — avoid dividing by zero
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    london_win_rate = (london_wins / london_trades * 100) if london_trades > 0 else 0
    ny_win_rate = (ny_wins / ny_trades * 100) if ny_trades > 0 else 0
    
    # Return all statistics as a dictionary
    return {
        'total_trades': total_trades,
        'total_wins': total_wins,
        'total_losses': total_losses,
        'win_rate': round(win_rate, 2),
        'average_r': round(avg_r, 2) if avg_r else 0,
        'total_r': round(total_r, 2) if total_r else 0,
        'london_trades': london_trades,
        'london_win_rate': round(london_win_rate, 2),
        'ny_trades': ny_trades,
        'ny_win_rate': round(ny_win_rate, 2)
    }  