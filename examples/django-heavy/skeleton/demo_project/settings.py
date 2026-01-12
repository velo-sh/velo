# Demo Project Settings for HIO-001 Django Heavyweight Demo
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = 'velo-hio-demo-secret-key-not-for-production'

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'heavy_app',  # Heavy app containing 200+ models
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',  # Use memory database to avoid file I/O
    }
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

USE_TZ = True
