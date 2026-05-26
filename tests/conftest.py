import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from api.db import configure_database, init_db
from api.main import app


@pytest.fixture(scope="session", autouse=True)
def test_db():
    db_fd, db_path = tempfile.mkstemp(prefix="test_", suffix=".db")
    os.close(db_fd)
    database_url = f"sqlite:///{db_path}"
    configure_database(database_url, connect_args={"check_same_thread": False})
    init_db()
    yield
    try:
        os.remove(db_path)
    except OSError:
        pass


@pytest.fixture
def client():
    return TestClient(app)
