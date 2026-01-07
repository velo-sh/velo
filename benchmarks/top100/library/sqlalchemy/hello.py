import sqlalchemy
engine = sqlalchemy.create_engine("sqlite:///:memory:")
print(f"SQLAlchemy version: {sqlalchemy.__version__}")