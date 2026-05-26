import os
from fastapi import Form, HTTPException, Request
from starlette.responses import RedirectResponse


def get_auth_settings():
    username = os.getenv("AUTH_USERNAME", "admin")
    password = os.getenv("AUTH_PASSWORD", "admin")
    secret_key = os.getenv("SESSION_SECRET_KEY", "change-me-please")
    return username, password, secret_key


def authenticate(username: str, password: str) -> bool:
    expected_username, expected_password, _ = get_auth_settings()
    return username == expected_username and password == expected_password


def require_login(request: Request):
    if request.session.get("user"):
        return True
    return False


def clear_session(request: Request):
    request.session.clear()


def login_form(request: Request):
    return {
        "request": request,
        "error": None,
    }


def login_payload(username: str = Form(...), password: str = Form(...)):
    return username, password
