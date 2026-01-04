# DEF-61-001: Django get_wsgi_application Not Detected

**Priority:** P1
**Status:** VERIFIED
**Reporter:** Agent A (Compliance)
**Assignee:** Developer
**Verified By:** QA Leader

## Summary
`detect_app.py` fails to identify Django applications initialized via `get_wsgi_application()` or `get_asgi_application()`. It only looks for class instantiation `Django()`, which is incorrect for standard Django projects.

## Reproduction
```python
# wsgi.py
import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
application = get_wsgi_application()
```

Running `detect_app.py` on this file returns no results.

## Root Cause Analysis
The `FRAMEWORK_PATTERNS` list in `detect_app.py` only includes `("Django", "Django")`. It lacks the standard factory functions used by Django.

## Suggested Fix
Update `FRAMEWORK_PATTERNS` to include:
- `("get_wsgi_application", "Django")`
- `("get_asgi_application", "Django")`

---
**QA Signature:** Velo QA Working Group
