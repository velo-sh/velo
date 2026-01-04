# Framework-Centric Verification (Battlefield Strategy)

## BATTLE-601: FastAPI
Test whether Velo's static graph correctly captures the transitive closure of:
- FastAPI -> Starlette -> Pydantic.
- Verify async routes and dependency injection (Depends) resolution.

## BATTLE-602: Flask
Test the dynamic nature of Flask:
- Blueprints registered in separate modules.
- Extensions (e.g., Flask-SQLAlchemy) that perform hidden imports.

## BATTLE-603: Django
The "Final Boss" of imports:
- Django App Registry: `apps.populate(settings.INSTALLED_APPS)` triggers many side-effect imports.
- ORM Models: Class-level attributes that trigger relational imports.
- Settings discovery: `DJANGO_SETTINGS_MODULE` environment variable handling.
