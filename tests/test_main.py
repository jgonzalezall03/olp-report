from fastapi import status
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from api.models import JiraProject


def test_root_redirects_to_dashboard(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in {status.HTTP_307_TEMPORARY_REDIRECT, status.HTTP_302_FOUND}
    assert "/dashboard" in response.headers["location"]


def test_login_page_shows_form(client):
    response = client.get("/login")
    assert response.status_code == status.HTTP_200_OK
    assert "Iniciar sesión" in response.text


def test_login_fails_with_invalid_credentials(client):
    response = client.post("/login", data={"username": "wrong", "password": "wrong"})
    assert response.status_code == status.HTTP_200_OK
    assert "Usuario o contraseña incorrectos" in response.text


def test_login_succeeds_and_redirects(client):
    response = client.post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/dashboard"


def test_active_filter_compiles_for_postgresql():
    statement = select(JiraProject.id).where(JiraProject.active.is_(True))
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "IS true" in compiled
