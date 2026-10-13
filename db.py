"""SQLite helpers: users + recommendation history."""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "pocketsmart.db"


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT,
            password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT, budget REAL, inputs TEXT, result TEXT,
            created TEXT DEFAULT CURRENT_TIMESTAMP);
        """)


def create_user(username, email, password_hash):
    try:
        with conn() as c:
            c.execute("INSERT INTO users(username,email,password) VALUES(?,?,?)",
                      (username, email, password_hash))
        return True
    except sqlite3.IntegrityError:
        return False


def get_user(username):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


def save_history(user_id, category, budget, inputs, result):
    with conn() as c:
        cur = c.execute(
            "INSERT INTO history(user_id,category,budget,inputs,result) VALUES(?,?,?,?,?)",
            (user_id, category, budget, json.dumps(inputs), json.dumps(result)))
        return cur.lastrowid


def list_history(user_id, limit=50):
    with conn() as c:
        return c.execute("SELECT * FROM history WHERE user_id=? ORDER BY id DESC LIMIT ?",
                         (user_id, limit)).fetchall()


def get_history(hid, user_id):
    with conn() as c:
        return c.execute("SELECT * FROM history WHERE id=? AND user_id=?",
                         (hid, user_id)).fetchone()
