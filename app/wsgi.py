"""Production WSGI entry point for Gunicorn.

The feed cache is process-local; run ONE Gunicorn worker, WITHOUT --preload.
The module is imported in the worker (after fork), where refresh may start.
"""
import threading

from app.main import app, worker

threading.Thread(target=worker, daemon=True, name="rss-feed-refresh").start()
