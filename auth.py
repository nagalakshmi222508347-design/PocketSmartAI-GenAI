"""Password hashing, JWT tokens and the current-user dependency."""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import Request

import db

load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ALGO = "HS256"
TOKEN_HOURS = 8


class NotAuthenticated(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"


def verify_password(password: str, stored: str) -> bool:
    salt, h = stored.split("$")
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return hmac.compare_digest(h, check)


def create_token(username: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode({"sub": username, "exp": exp}, SECRET_KEY, algorithm=ALGO)


def authenticate(username: str, password: str):
    user = db.get_user(username)
    if user and verify_password(password, user["password"]):
        return user
    return None


def get_current_user(request: Request):
    """Reads JWT from the cookie (browser) or Authorization header (API)."""
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else None
    if not token:
        raise NotAuthenticated()
    try:
        username = jwt.decode(token, SECRET_KEY, algorithms=[ALGO])["sub"]
    except jwt.PyJWTError:
        raise NotAuthenticated()
    user = db.get_user(username)
    if not user:
        raise NotAuthenticated()
    return user


def get_optional_user(request: Request):
    try:
        return get_current_user(request)
    except NotAuthenticated:
        return None
