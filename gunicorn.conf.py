import os

# Bind / workers / threads. Render supplies PORT at runtime; keep the local
# default so the same command remains convenient outside its environment.
bind = os.getenv("BIND") or f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers = int(os.getenv("WEB_CONCURRENCY", "1"))  # Agent memory is process-local.
threads = int(os.getenv("WEB_THREADS", "2"))

# Worker class & timeouts
worker_class = "gthread"
timeout = int(os.getenv("WEB_TIMEOUT", "90"))
graceful_timeout = int(os.getenv("WEB_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("WEB_KEEPALIVE", "5"))

# Logging
loglevel = os.getenv("LOG_LEVEL", "info")
accesslog = "-"   # stdout
# Never log the query string: provider verification/OAuth callbacks contain secrets.
access_log_format = '%(t)s %(m)s %(U)s %(s)s %(b)s %(L)s'
errorlog = "-"    # stderr
capture_output = True

# Security / proxy
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1,::1")
proxy_protocol = False
umask = 0o077

# Preload to reduce per-worker startup
preload_app = True
# The preloaded master uses short-lived DB connections. Pool sockets and
# maintenance threads are created lazily in each forked worker only.
os.environ['V7_PRELOAD_MASTER_PID'] = str(os.getpid())

def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)
    if os.getenv('V7_ASYNC_TELEMETRY', 'true' if os.getenv('RENDER') == 'true' else 'false') == 'true':
        from service.telemetry_outbox import start
        start()

def when_ready(server):
    server.log.info("Gunicorn is ready. Spawning workers")

def worker_int(worker):
    worker.log.info("Worker received INT or QUIT signal")

def worker_abort(worker):
    worker.log.info("Worker received SIGABRT signal")


def worker_exit(server, worker):
    from service.telemetry_outbox import shutdown
    from service.postgres_pool import close_pools
    shutdown()
    close_pools()
