#!/bin/sh
set -eu
exec gunicorn -c gunicorn.conf.py scripts.billing_sandbox:app
