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

    # NEW: instead of hardcoding 'London' and 'New York', ask the database which
    # session names actually exist in the trades table -- works for any number of sessions
    cursor.execute('SELECT DISTINCT session FROM trades')
    all_sessions = [row[0] for row in cursor.fetchall()]  # e.g. ['Asian KZ', 'London Open KZ', ...]

    # build a win-rate breakdown for EVERY session that actually has trades, not just two
    session_stats = {}  # will look like {'Asian KZ': {'trades': 5, 'wins': 3, 'win_rate': 60.0}, ...}
    for session_name in all_sessions:
        cursor.execute('SELECT COUNT(*) FROM trades WHERE session = ?', (session_name,))
        session_trades = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM trades WHERE session = ? AND result = 'WIN'", (session_name,))
        session_wins = cursor.fetchone()[0]

        session_win_rate = (session_wins / session_trades * 100) if session_trades > 0 else 0
        session_stats[session_name] = {
            'trades': session_trades,
            'wins': session_wins,
            'win_rate': round(session_win_rate, 2),
        }

    conn.close()

    # Calculate overall win rate safely -- avoid dividing by zero
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

    return {
        'total_trades': total_trades,
        'total_wins': total_wins,
        'total_losses': total_losses,
        'win_rate': round(win_rate, 2),
        'average_r': round(avg_r, 2) if avg_r else 0,
        'total_r': round(total_r, 2) if total_r else 0,
        'session_stats': session_stats,   # NEW: replaces the old london_trades/ny_trades fields
    }