from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import psycopg2
import os

app = FastAPI()

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@db:5432/app")


def get_db():
    return psycopg2.connect(DATABASE_URL)


class TodoCreate(BaseModel):
    title: str


class TodoResponse(BaseModel):
    id: int
    title: str
    done: bool


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/todos")
def list_todos():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, title, done FROM todos ORDER BY id")
    todos = [{"id": r[0], "title": r[1], "done": r[2]} for r in cur.fetchall()]
    cur.close()
    db.close()
    return todos


@app.post("/api/todos", status_code=201)
def create_todo(todo: TodoCreate):
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "INSERT INTO todos (title) VALUES (%s) RETURNING id, title, done",
        (todo.title,),
    )
    row = cur.fetchone()
    db.commit()
    cur.close()
    db.close()
    return {"id": row[0], "title": row[1], "done": row[2]}


@app.get("/api/todos/{todo_id}")
def get_todo(todo_id: int):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, title, done FROM todos WHERE id = %s", (todo_id,))
    row = cur.fetchone()
    cur.close()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"id": row[0], "title": row[1], "done": row[2]}
