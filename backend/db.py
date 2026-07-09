"""StudySphere AI — database layer (SQLite).
Zero-setup persistent database. The file studysphere.db is created automatically.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "studysphere.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    goal TEXT DEFAULT '',
    grade TEXT DEFAULT '',
    xp INTEGER DEFAULT 0,
    streak INTEGER DEFAULT 0,
    last_active TEXT DEFAULT '',
    created TEXT DEFAULT (date('now'))
);
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL,              -- 'user' | 'assistant'
    agent TEXT DEFAULT '',           -- which specialist answered
    content TEXT NOT NULL,
    ts TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS quizzes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    topic TEXT NOT NULL,
    score INTEGER NOT NULL,
    total INTEGER NOT NULL,
    date TEXT DEFAULT (date('now'))
);
CREATE TABLE IF NOT EXISTS weak_topics (
    user_id INTEGER NOT NULL REFERENCES users(id),
    topic TEXT NOT NULL,
    misses INTEGER DEFAULT 1,
    PRIMARY KEY (user_id, topic)
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    subject TEXT NOT NULL,
    created TEXT DEFAULT (date('now'))
);
CREATE TABLE IF NOT EXISTS plan_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    day INTEGER NOT NULL,
    topic TEXT NOT NULL,
    text TEXT NOT NULL,
    done INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    body TEXT DEFAULT '',
    ts TEXT DEFAULT (date('now'))
);
CREATE INDEX IF NOT EXISTS idx_chats_user ON chats(user_id, id);
CREATE INDEX IF NOT EXISTS idx_quiz_user ON quizzes(user_id, id);
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript(SCHEMA)


def row_to_dict(row):
    return dict(row) if row else None
