"""
Django settings for the Binh Dinh Gia Ouargla club platform.
"""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-6t@up-@6erncqn-suxsp9)%g29_h^vhjih=rj@)1%y0bqqwo72',
)

DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'accounts',
    'organization',
    'registrations',
    'competitions',
    'community',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Serves everything in STATIC_ROOT. Django itself only serves static files
    # while DEBUG is on, and a cPanel Python app hands every URL to Passenger,
    # so without this the admin loads with no stylesheet at all. Directly after
    # SecurityMiddleware is where WhiteNoise has to sit.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# SQLite while developing; MySQL in production, entirely from the environment
# so no credential is ever written into a file that gets committed. Set DB_NAME
# (plus user, password, host) in .env and the app switches over on its own.
if os.environ.get('DB_NAME'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ['DB_NAME'],
            'USER': os.environ.get('DB_USER', ''),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '3306'),
            'OPTIONS': {
                # utf8mb4, or Arabic names and Vietnamese diacritics are stored
                # wrong; the strict mode catches silent truncation.
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
            'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '60')),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Algiers'
USE_I18N = True
USE_TZ = True


STATIC_URL = 'static/'
# Where `collectstatic` puts the Django admin's own CSS on the server.
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Hashes each file's contents into its name and serves it with a one-year
# cache. 'Compressed' only, not the 'Manifest' variant: that one refuses to
# start if any stylesheet references a file that is not there, which would turn
# a missing icon into a dead site.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'storage' / 'uploads'

# Registration documents under MEDIA_ROOT are private — they only ever leave
# through an authenticated view. Community photos and post media are meant to
# be seen by anyone, so they live in their own root that IS served directly.
# Keeping the two apart means switching on public serving can never expose a
# candidate's paperwork.
PUBLIC_MEDIA_URL = '/public-media/'
PUBLIC_MEDIA_ROOT = BASE_DIR / 'storage' / 'public'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Registration document uploads: keep small clerical limits sane (10 MB/file).
# Post videos are the largest thing the platform accepts, hence the headroom.
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
COMMUNITY_IMAGE_MAX_BYTES = 8 * 1024 * 1024
COMMUNITY_VIDEO_MAX_BYTES = 64 * 1024 * 1024
# A visitor with no account can still comment, so the only brake is the clock.
COMMUNITY_COMMENT_WINDOW_SECONDS = 120
COMMUNITY_COMMENT_MAX_PER_WINDOW = 3

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.AllowAny',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
}

CORS_ALLOWED_ORIGINS = os.environ.get(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:5173,http://127.0.0.1:5173',
).split(',')


# ── Production hardening ────────────────────────────────────────────────────
# Only applied with DEBUG off, so local development is untouched. A shared host
# terminates TLS at the web server and forwards the original scheme in this
# header; without the next line Django thinks every request is plain HTTP and
# redirects in a loop.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True') == 'True'
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    X_FRAME_OPTIONS = 'DENY'
    # HSTS is deliberately opt-in: switching it on tells browsers to refuse
    # plain HTTP for this domain for months, which is painful to undo if the
    # certificate is not ready yet.
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))
    if SECURE_HSTS_SECONDS:
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True
        SECURE_HSTS_PRELOAD = True

# The dashboard posts from the frontend's domain, which is a different origin.
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]

# Uploads on a shared host: keep a lid on what a single request may push.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000
