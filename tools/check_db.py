"""Check that the database in `.env` is reachable, and explain it if not.

    venv/Scripts/python.exe tools/check_db.py

Run this before migrating. cPanel refuses outside connections until your IP is
added under Remote MySQL, and the error MySQL returns for that is not obvious,
so each likely cause is spelled out below.
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.db import connection  # noqa: E402

config = settings.DATABASES['default']

if 'sqlite' in config['ENGINE']:
    sys.exit(
        'Still pointing at the local SQLite file.\n'
        'Put DB_NAME, DB_USER, DB_PASSWORD and DB_HOST in backend/.env first '
        '(copy .env.example).'
    )

print(f"database : {config['NAME']}")
print(f"user     : {config['USER']}")
print(f"host     : {config['HOST']}:{config['PORT']}")
print()

try:
    connection.ensure_connection()
except Exception as exc:  # noqa: BLE001 - the whole point is to explain it
    message = str(exc)
    print('Could not connect.\n')
    print(f'  {message}\n')

    if "Can't connect" in message or 'timed out' in message or '2003' in message:
        print('Most likely: your IP is not allowed in yet.')
        print('  cPanel > Remote MySQL > add your current public IP address.')
        print('  Also check DB_HOST — from your PC it is the server hostname or')
        print('  its IP, never "localhost".')
    elif 'Access denied' in message or '1045' in message:
        print('Most likely: wrong user or password, or the user was never added')
        print('to the database.')
        print('  cPanel > MySQL Databases > Add User To Database > ALL PRIVILEGES.')
        print('  Remember cPanel prefixes both names with your account name.')
    elif 'Unknown database' in message or '1049' in message:
        print('The user and password work, but that database does not exist.')
        print('  Check DB_NAME — it includes the cPanel prefix, e.g. user_bdg.')
    sys.exit(1)

with connection.cursor() as cursor:
    cursor.execute('SELECT VERSION()')
    version = cursor.fetchone()[0]

tables = connection.introspection.table_names()
print(f'Connected. MySQL {version}')
print(f'Tables present: {len(tables)}')

if not tables:
    print('\nEmpty database — run:  python manage.py migrate')
elif 'registrations_registration' in tables:
    from registrations.models import Registration  # noqa: E402

    print(f'Already migrated. Registrations stored: {Registration.objects.count()}')
else:
    print('\nTables exist but not the platform\'s — run:  python manage.py migrate')
