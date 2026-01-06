import django
from django.conf import settings

# Minimal configuration to boostrap Django
if not settings.configured:
    settings.configure(INSTALLED_APPS=[])
    
django.setup()
print(f"Django version: {django.get_version()}")