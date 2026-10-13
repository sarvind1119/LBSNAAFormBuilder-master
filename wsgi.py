"""
wsgi.py - Production entry point: `gunicorn wsgi:app`.
Initializes the database and models once per worker process.
"""

from app import app, initialize_app

initialize_app()
