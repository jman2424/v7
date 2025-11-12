import multiprocessing
import os

# Bind / workers / threads
bind = os.getenv("BIND", "0.0.0.0:10000")
workers = int(os.getenv("WEB_CONCURRENCY", str(max(2, multiprocessing.cpu_count() // 2))))
threads = int(os.getenv("WEB_THREADS", "2"))

# Worker class & timeouts
worker_class = "gthread"
timeout = int(os.getenv("WEB_TIMEOUT", "90"))
graceful_timeout = int(os.getenv("WEB_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("WEB_KEEPALIVE", "5"))

# Logging
loglevel = os.getenv("LOG_LEVEL", "info")
accesslog = "-"   # stdout
errorlog = "-"    # stderr
capture_output = True

# Security / proxy
forwarded_allow_ips = "*"
proxy_protocol = False

# Preload to reduce per-worker startup
preload_app = True

def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def when_ready(server):
    server.log.info("Gunicorn is ready. Spawning workers")

def worker_int(worker):
    worker.log.info("Worker received INT or QUIT signal")

def worker_abort(worker):
    worker.log.info("Worker received SIGABRT signal")
