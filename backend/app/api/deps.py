from typing import Annotated

from fastapi import Depends, Request

from app.infrastructure.db.engine import Database


def get_database(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


DatabaseDep = Annotated[Database, Depends(get_database)]
