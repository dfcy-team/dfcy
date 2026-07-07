#!/bin/sh
set -e

python manage.py check

exec "$@"
