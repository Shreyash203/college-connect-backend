from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.models import User


def sync_auth_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    if User.__tablename__ not in existing_tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns(User.__tablename__)}
    missing_columns = []

    for column in missing_columns:
        if column.name in existing_columns:
            continue

        column_type = engine.dialect.type_compiler_instance.process(column.type)
        statement = text(
            f"ALTER TABLE {User.__tablename__} ADD COLUMN {column.name} {column_type}"
        )
        with engine.begin() as connection:
            connection.execute(statement)
