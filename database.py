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

     