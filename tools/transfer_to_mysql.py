"""Copy the club's existing records from the local SQLite file into MySQL.

Run it from the `backend` folder, from your PC, with `.env` already pointing at
the cPanel database:

    venv/Scripts/python.exe tools/transfer_to_mysql.py

What it does, in order:

  1. reads every row from db.sqlite3 (the file on your PC, untouched)
  2. checks the MySQL database is reachable and its tables are migrated
  3. refuses to continue if MySQL already holds registrations, so a second run
     cannot duplicate the club's data
  4. loads the rows into MySQL and reports what arrived

Content types and permissions are skipped on purpose: Django recreates those
during `migrate`, and copying them across collides with the fresh ones.
"""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
DUMP = BASE_DIR / 'tools' / '_transfer.json'

# Everything the club owns. Auth users come first: profiles point at them.
APPS = [
    'auth.user', 'auth.group',
    'organization', 'registrations', 'competitions', 'community',
]


def run(args, env=None, capture=False):
    # PYTHONUTF8 turns on Python's UTF-8 mode in the child process. Without
    # it, Windows defaults to cp1252 for both the console and any file Django
    # opens itself, and `dumpdata` dies the moment it meets an Arabic name —
    # even when writing to a file with -o, because Django opens that file with
    # the locale encoding.
    merged = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', **(env or {})}
    result = subprocess.run(
        [PYTHON, *args], cwd=BASE_DIR, env=merged,
        capture_output=capture, text=True, encoding='utf-8',
    )
    if result.returncode != 0:
        # Show what the child actually said; a bare CalledProcessError hides it.
        detail = (result.stderr or result.stdout or '').strip()
        sys.exit('\n{} failed:\n{}'.format(' '.join(args), detail))
    return result


def manage(args, env=None, capture=False):
    return run(['manage.py', *args], env=env, capture=capture)


def main():
    if not (BASE_DIR / 'db.sqlite3').exists():
        sys.exit('No db.sqlite3 here — nothing to copy.')

    if not os.environ.get('DB_NAME'):
        # dotenv is loaded by settings, but this script needs to know too.
        from dotenv import dotenv_values
        values = dotenv_values(BASE_DIR / '.env')
        if not values.get('DB_NAME'):
            sys.exit('Set DB_NAME (and user, password, host) in backend/.env first.')
        os.environ.update({k: v for k, v in values.items() if v is not None})

    print(f"target database: {os.environ['DB_NAME']} at {os.environ.get('DB_HOST')}")

    # 1. Read from SQLite. Unsetting DB_NAME sends settings back to the file.
    sqlite_env = {k: '' for k in ('DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST')}
    print('reading the local records...')
    # `-o` makes Django write the file itself, in UTF-8. Piping through stdout
    # would hand the Arabic and Vietnamese text to the console's encoding.
    manage(
        ['dumpdata', *APPS, '--natural-foreign', '--natural-primary',
         '--indent', '2', '-o', str(DUMP)],
        env=sqlite_env,
    )
    rows = json.loads(io.open(DUMP, encoding='utf-8').read())
    print(f'  {len(rows)} rows read from db.sqlite3')

    # 2 & 3. The target must be migrated, and must not already hold data.
    print('checking the target database...')
    count = manage(['shell', '-c', (
        'from registrations.models import Registration;'
        'print(Registration.objects.count())'
    )], capture=True).stdout.strip().splitlines()[-1]
    if count != '0':
        DUMP.unlink(missing_ok=True)
        sys.exit(
            f'MySQL already holds {count} registrations. Stopping so this cannot '
            'duplicate them. Empty the database first if you meant to start over.'
        )

    # 4. Load.
    print('copying into MySQL...')
    manage(['loaddata', str(DUMP)])

    summary = manage(['shell', '-c', (
        'from registrations.models import Registration;'
        'from organization.models import Club, Center, UserProfile;'
        'from community.models import Post;'
        'print(Registration.objects.count(), Club.objects.count(), '
        'Center.objects.count(), UserProfile.objects.count(), Post.objects.count())'
    )], capture=True).stdout.strip().splitlines()[-1]
    regs, clubs, branches, staff, posts = summary.split()
    print(
        f'\ndone — in MySQL now: {regs} registrations, {clubs} clubs, '
        f'{branches} branches, {staff} staff accounts, {posts} posts'
    )
    print('\nThe uploaded files are NOT copied by this script. Upload these two')
    print('folders to the server with cPanel File Manager or FTP:')
    print('  backend/storage/uploads   (candidates\' documents — keep private)')
    print('  backend/storage/public    (carousel and post media)')
    DUMP.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
