# Import pytest for running tests
import pytest

# Import the Flask app so we can test its routes
from app import app

# Import the database functions so we can set up test data
import sqlite3
import os

# ── Test Setup ──

@pytest.fixture
# A fixture is a function that runs before each test to set things up
def client():
    # Put the app in testing mode — no real server needed
    app.config['TESTING'] = True
    
    # Use a separate test database so we don't mess up real data
    app.config['DATABASE'] = 'test_goat.db'
    
    # Create a test client — this simulates sending HTTP requests
    with app.test_client() as client:
        yield client
    
    # Clean up — delete the test database after tests finish
    if os.path.exists('test_goat.db'):
        os.remove('test_goat.db')

# ── Tests ──

# Test 1 — Homepage loads correctly
def test_home(client):
    response = client.get('/')
    # 200 means the page loaded successfully
    assert response.status_code == 200

# Test 2 — Dashboard loads correctly
def test_dashboard(client):
    response = client.get('/dashboard')
    assert response.status_code == 200

# Test 3 — POST a valid trade returns 201
def test_post_trade(client):
    # This is the trade data we send
    trade = {
        "pair": "EURUSD",
        "session": "London",
        "entry": 1.14447,
        "stop_loss": 1.14147,
        "take_profit": 1.14747,
        "result": "WIN",
        "r_multiple": 2.0,
        "account": "Account 1",
        "date": "2026-06-27",
        "notes": "Test trade"
    }
    
    # Send the POST request with JSON data
    response = client.post('/trades',
        json=trade,
        content_type='application/json'
    )
    
    # 201 means the trade was created successfully
    assert response.status_code == 201
    
    # Check the response message
    data = response.get_json()
    assert data['message'] == 'Trade saved successfully'

# Test 4 — GET all trades returns 200
def test_get_trades(client):
    response = client.get('/trades')
    assert response.status_code == 200

# Test 5 — GET stats returns 200
def test_get_stats(client):
    response = client.get('/stats')
    assert response.status_code == 200

# Test 6 — POST trade with missing field returns error
def test_post_trade_missing_field(client):
    # Missing 'pair' field deliberately
    incomplete_trade = {
        "session": "London",
        "entry": 1.14447,
        "stop_loss": 1.14147,
        "take_profit": 1.14747,
        "result": "WIN",
        "r_multiple": 2.0,
        "account": "Account 1",
        "date": "2026-06-27"
    }
    
    response = client.post('/trades',
        json=incomplete_trade,
        content_type='application/json'
    )
    
    # Should return 400 Bad Request or 500 error — not 201
    assert response.status_code != 201

# Test 7 — News feed loads correctly
def test_news_feed(client):
    response = client.get('/news')
    assert response.status_code == 200