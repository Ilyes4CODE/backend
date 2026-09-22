# Binh Dinh Gia — API

Django REST API for the Binh Dinh Gia club platform: online registration,
candidate management across wilayas, training groups, competitions, certificates,
member badges and a public community feed.

The frontend lives in its own repository.

## Access levels

Three levels. Each sees its own level and everything below it — never above,
never sideways. Enforced in the API, not only in the dashboard.

| | Sees |
|---|---|
| National administrator | Every wilaya and club |
| Club president | Their club and all of its branches (فروع) |
| Branch manager | One branch |

## Running it locally

```bash
python -m venv venv
venv/Scripts/activate          # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

With no `.env` it uses SQLite and is ready to go. Tests: `python manage.py test`.

## Deploying to cPanel shared hosting

### 1. Create the database

cPanel → **MySQL® Databases**:

1. Create a database, e.g. `bdg`. cPanel prefixes it with your account name, so
   the real name becomes something like `cpaneluser_bdg`.
2. Create a user with a strong password — note both down.
3. Under **Add User To Database**, add the user to the database with
   **ALL PRIVILEGES**.

### 2. Let your PC reach it (only needed to migrate from your machine)

cPanel → **Remote MySQL** → add your current public IP address. Without this,
the host refuses connections from outside the server.

### 3. Point the project at it and create the tables

In `backend/.env` on your PC (copy `.env.example`):

```ini
DB_NAME=cpaneluser_bdg
DB_USER=cpaneluser_bdguser
DB_PASSWORD=...
DB_HOST=your-server-hostname-or-ip     # not "localhost" from your PC
```

Then:

```bash
python manage.py migrate
```

### 4. Copy the existing records across

```bash
python tools/transfer_to_mysql.py
```

It reads `db.sqlite3`, refuses to run if MySQL already holds registrations, and
reports what arrived. Uploaded files are not copied — see step 6.

### 5. Put the code on the server

Upload the repository (Git clone or File Manager), then cPanel →
**Setup Python App**:

- Python version: 3.10 or newer
- Application root: where you uploaded it
- Application startup file: `passenger_wsgi.py`
- Application Entry point: `application`

Then, in that app's virtualenv:

```bash
pip install -r requirements.txt
python manage.py collectstatic --noinput
```

Create `.env` on the server from `.env.example`, this time with
`DB_HOST=localhost`, a **fresh** `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, and
your real domains in `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` and
`CSRF_TRUSTED_ORIGINS`.

Restart the app from cPanel after any change — Passenger caches the code.

### 6. Upload the files that are not in Git

Candidates' documents and site media are deliberately excluded from the
repository. Copy these two folders to the server:

```
backend/storage/uploads   candidates' identity documents — keep private
backend/storage/public    carousel images and post media — served publicly
```

`storage/uploads` must **not** be reachable over the web. It is served only
through an authenticated endpoint; if your setup exposes the folder directly,
block it with a `.htaccess` containing `Require all denied`.

### 7. Check it

```
https://your-api-domain/api/settings/
```

should answer with JSON. Then sign in from the dashboard.

## What is deliberately not in this repository

- `.env` — every secret and database credential
- `db.sqlite3` — the club's records
- `storage/` — candidates' identity documents and photos

Nothing here identifies a member. Keep it that way.
