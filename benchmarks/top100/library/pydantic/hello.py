import pydantic


class User(pydantic.BaseModel):
    id: int


print(f"Pydantic version: {pydantic.VERSION}")
