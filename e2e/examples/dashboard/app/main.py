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


@app.get("/api/metrics")
def metrics():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*), COALESCE(SUM(amount),0), COUNT(DISTINCT customer_name) FROM orders"
    )
    total, revenue, customers = cur.fetchone()
    cur.close()
    conn.close()
    avg = float(revenue) / total if total else 0
    return {
        "total_orders": total,
        "revenue": float(revenue),
        "customers": customers,
        "avg_order_value": round(avg, 2),
    }


@app.get("/api/orders")
def list_orders():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, customer_name, product, amount, status, created_at "
        "FROM orders ORDER BY created_at DESC"
    )
    orders = [
        {
            "id": r[0],
            "customer_name": r[1],
            "product": r[2],
            "amount": float(r[3]),
            "status": r[4],
            "created_at": r[5].isoformat(),
        }
        for r in cur.fetchall()
    ]
    cur.close()
    conn.close()
    return orders


@app.get("/", response_class=HTMLResponse)
def index():
    html = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html) as f:
        return f.read()
