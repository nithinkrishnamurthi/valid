import os

import psycopg2
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()
DATABASE_URL = os.environ["DATABASE_URL"]


def get_db():
    return psycopg2.connect(DATABASE_URL)


@app.get("/health")
def health():
    conn = get_db()
    conn.close()
    return {"status": "ok"}


@app.get("/api/tasks")
def list_tasks():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, assignee, priority, status, created_at "
        "FROM tasks ORDER BY created_at"
    )
    tasks = [
        {
            "id": r[0],
            "title": r[1],
            "assignee": r[2],
            "priority": r[3],
            "status": r[4],
            "created_at": r[5].isoformat(),
        }
        for r in cur.fetchall()
    ]
    cur.close()
    conn.close()
    return tasks


@app.get("/api/board")
def board():
    """Tasks grouped by column."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, assignee, priority, status "
        "FROM tasks ORDER BY created_at"
    )
    columns = {"backlog": [], "in_progress": [], "done": []}
    for r in cur.fetchall():
        col = columns.get(r[4], columns["backlog"])
        col.append({"id": r[0], "title": r[1], "assignee": r[2], "priority": r[3]})
    cur.close()
    conn.close()
    return columns


@app.get("/", response_class=HTMLResponse)
def index():
    html = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html) as f:
        return f.read()
