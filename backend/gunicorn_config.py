"""
Gunicorn configuration for production deployment.
Used by: gunicorn -c gunicorn_config.py app.main:app
"""

import os
import multiprocessing

# Socket binding
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"

# Worker processes
workers = int(os.environ.get("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
worker_class = "uvicorn.workers.UvicornWorker"

# Timeouts
timeout = 120
keepalive = 5

# Logging
accesslog = "-"  # stdout
errorlog = "-"   # stderr
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# Graceful shutdown
graceful_timeout = 30

# Preload app for faster startup
preload_app = True

# Max requests per worker to prevent memory leaks
max_requests = 1000
max_requests_jitter = 50
