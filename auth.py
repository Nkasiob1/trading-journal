# auth.py
# Simple password protection for GOAT
# Single user authentication — only you can access your trades

from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from flask import request, redirect, url_for
import os
from dotenv import load_dotenv

load_dotenv()

# ── USER CLASS ──
# Flask-Login requires a User class
# Since GOAT has only one user, we keep this simple

class User(UserMixin):
    def __init__(self, id):
        self.id = id

# The single GOAT user
goat_user = User(id='kasi')

# ── LOGIN MANAGER SETUP ──
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access GOAT.'

@login_manager.user_loader
def load_user(user_id):
    # Only one valid user exists
    if user_id == 'kasi':
        return goat_user
    return None

def check_credentials(username, password):
    """
    Verifies username and password against environment variables.
    Credentials are never hardcoded — always read from .env
    """
    correct_username = os.getenv('GOAT_USERNAME')
    correct_password = os.getenv('GOAT_PASSWORD')
    return username == correct_username and password == correct_password