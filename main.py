"""
Jason Seller X-Ray — Backend API Server
쿠팡 상품 재고 추적 및 판매량 추정
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import json
import os
import re
import time
import random
import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager

app = FastAPI(title="Jason X-Ray API", version="1.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB_PATH = os.environ.get("DB_PATH", "xray.db")

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS products (
            pid TEXT PRIMARY KEY, name TEXT, price INTEGER DEFAULT 0,
            rating REAL DEFAULT 0, review_count INTEGER DEFAULT 0, updated_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS stock_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT NOT NULL,
            stock INTEGER NOT NULL, price INTEGER DEFAULT 0,
            review_count INTEGER DEFAULT 0, recorded_at TEXT NOT NULL,
            UNIQUE(pid, recorded_at))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tracking (
            pid TEXT PRIMARY KEY, url TEXT, added_at TEXT, active INTEGER DEFAULT 1)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_pid ON stock_history(pid)")
        conn.commit()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

async def fetch_product(pid: str) -> dict:
    url = f"https://www.coupang.com/vp/products/{pid}"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            await asyncio.sleep(random.uniform(1, 3))
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code != 200: return None
            html = resp.text
            data = {"pid": pid}
            m = re.search(r'<h1[^>]*class="prod-buy-header__title"[^>]*>([^<]+)', html)
            if m: data["name"] = m.group(1).strip()
            m = re.search(r'total-price[^>]*>[\s]*<strong>([^<]+)', html)
            if m: data["price"] = int(re.sub(r'[^0-9]', '', m.group(1)))
            m = re.search(r'count-num[^>]*>\(?([\d,]+)\)?', html)
            if m: data["review_count"] = int(m.group(1).replace(",", ""))
            m = re.search(r'"maxOrderableCount"\s*:\s*(\d+)', html)
            if m: data["stock"] = int(m.group(1))
            else: data["stock"] = 0
            return data
    except Exception as e:
        print(f"[Error] {pid}: {e}")
        return None

def save_crawl(pid, data):
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        conn.execute("""INSERT OR REPLACE INTO products (pid,name,price,rating,review_count,updated_at)
            VALUES (?,?,?,?,?,?)""", (pid, data.get("name",""), data.get("price",0),
            data.get("rating",0), data.get("review_count",0), today))
        conn.execute("""INSERT OR REPLACE INTO stock_history (pid,stock,price,review_count,recorded_at)
            VALUES (?,?,?,?,?)""", (pid, data.get("stock",0), data.get("price",0),
            data.get("review_count",0), today))
        conn.execute("""INSERT OR IGNORE INTO tracking (pid,url,added_at,active)
            VALUES (?,?,?,1)""", (pid, f"https://www.coupang.com/vp/products/{pid}", datetime.now().isoformat()))
        conn.commit()

# ── API ──
@app.get("/")
def root():
    return {"service": "Jason X-Ray API", "status": "running"}

@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.post("/api/track")
def add_track(pid: str, url: str = ""):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO tracking (pid,url,added_at,active) VALUES (?,?,?,1)",
            (pid, url or f"https://www.coupang.com/vp/products/{pid}", datetime.now().isoformat()))
        conn.commit()
    return {"ok": True, "pid": pid}

@app.delete("/api/track/{pid}")
def remove_track(pid: str):
    with get_db() as conn:
        conn.execute("UPDATE tracking SET active=0 WHERE pid=?", (pid,))
        conn.commit()
    return {"ok": True}

@app.get("/api/track")
def list_track():
    with get_db() as conn:
        rows = conn.execute("""SELECT t.pid,t.url,t.added_at,p.name,p.price,p.review_count
            FROM tracking t LEFT JOIN products p ON t.pid=p.pid WHERE t.active=1
            ORDER BY t.added_at DESC""").fetchall()
    return [dict(r) for r in rows]

@app.get("/api/product/{pid}")
def get_product(pid: str):
    with get_db() as conn:
        product = conn.execute("SELECT * FROM products WHERE pid=?", (pid,)).fetchone()
        since = (datetime.now() - timedelta(days=28)).strftime("%Y-%m-%d")
        history = conn.execute("""SELECT stock,price,review_count,recorded_at FROM stock_history
            WHERE pid=? AND recorded_at>=? ORDER BY recorded_at ASC""", (pid, since)).fetchall()
    if not product:
        raise HTTPException(404, "Not found. Crawl first: POST /api/crawl/{pid}")
    history = [dict(h) for h in history]
    product = dict(product)
    sales = 0
    if len(history) >= 2:
        for i in range(1, len(history)):
            diff = history[i-1]["stock"] - history[i]["stock"]
            if diff > 0: sales += diff
        review_diff = history[-1]["review_count"] - history[0]["review_count"]
        if review_diff > 0:
            review_sales = int(review_diff / 0.04)
            sales = max(sales, review_sales)
    views = int(sales / 0.03) if sales > 0 else 0
    return {**product, "history": history, "estimated_sales_28d": sales,
            "estimated_views_28d": views, "data_points": len(history)}

@app.get("/api/product/{pid}/history")
def get_history(pid: str, days: int = Query(28, ge=1, le=365)):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_db() as conn:
        rows = conn.execute("""SELECT stock,price,review_count,recorded_at FROM stock_history
            WHERE pid=? AND recorded_at>=? ORDER BY recorded_at ASC""", (pid, since)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/crawl/{pid}")
async def crawl_now(pid: str):
    data = await fetch_product(pid)
    if not data: raise HTTPException(502, "Crawl failed")
    save_crawl(pid, data)
    return {"ok": True, "data": data}

@app.post("/api/crawl-all")
async def crawl_all():
    with get_db() as conn:
        rows = conn.execute("SELECT pid FROM tracking WHERE active=1").fetchall()
    results = []
    for row in rows:
        pid = row["pid"]
        data = await fetch_product(pid)
        if data:
            save_crawl(pid, data)
            results.append({"pid": pid, "stock": data.get("stock"), "ok": True})
        else:
            results.append({"pid": pid, "ok": False})
        await asyncio.sleep(random.uniform(2, 5))
    return {"crawled": len(results), "results": results}

@app.get("/api/stats")
def get_stats():
    with get_db() as conn:
        t = conn.execute("SELECT COUNT(*) as c FROM tracking WHERE active=1").fetchone()["c"]
        p = conn.execute("SELECT COUNT(*) as c FROM products").fetchone()["c"]
        r = conn.execute("SELECT COUNT(*) as c FROM stock_history").fetchone()["c"]
        l = conn.execute("SELECT MAX(recorded_at) as l FROM stock_history").fetchone()["l"]
    return {"tracking": t, "products": p, "records": r, "latest": l}

@app.on_event("startup")
def startup():
    init_db()
    print("[Server] Jason X-Ray API started")
