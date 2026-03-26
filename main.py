"""
Jason Seller X-Ray — Backend API Server v2.5 (Final Viewer)
수정 사항: 
1. 브라우저 주소창에서 직접 데이터를 볼 수 있도록 GET /api/report 추가
2. 데이터 초기화 기능 추가
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import sqlite3, os, re
from datetime import datetime
from contextlib import contextmanager

app = FastAPI(title="Jason X-Ray API", version="2.5")

# CORS 전면 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.environ.get("DB_PATH", "/tmp/xray.db")

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try: yield conn
    finally: conn.close()

def init_db():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS products (
            pid TEXT PRIMARY KEY, name TEXT, price INTEGER, updated_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS stock_history (
            pid TEXT, stock INTEGER, price INTEGER, recorded_at TEXT)""")
        conn.commit()

@app.get("/")
def root(): 
    return {"status": "online", "mode": "receiver", "version": "2.5"}

# [추가] 브라우저 주소창에서 저장된 데이터를 확인하는 경로
@app.get("/api/report")
async def get_all_data():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY updated_at DESC").fetchall()
    return {"ok": True, "count": len(rows), "data": [dict(r) for r in rows]}

@app.post("/api/report")
async def report_data(request: Request):
    """브라우저 콘솔에서 수집한 데이터를 저장[cite: 2]"""
    try:
        data = await request.json()
        pid = str(data.get("pid", ""))
        if not pid: return {"ok": False, "msg": "No PID"}

        today = datetime.now().strftime("%Y-%m-%d %H:00")
        with get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO products (pid, name, price, updated_at) VALUES (?,?,?,?)",
                (pid, data.get("name", "Unknown"), data.get("price", 0), today))
            conn.execute("INSERT OR REPLACE INTO stock_history (pid, stock, price, recorded_at) VALUES (?,?,?,?)",
                (pid, data.get("stock", 0), data.get("price", 0), today))
            conn.commit()
        
        print(f"✅ Data Saved: {pid}")
        return {"ok": True, "pid": pid}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

# [추가] 테스트용 데이터 초기화 (필요할 때만 사용)[cite: 2]
@app.get("/api/clear")
async def clear_db():
    with get_db() as conn:
        conn.execute("DELETE FROM products")
        conn.execute("DELETE FROM stock_history")
        conn.commit()
    return {"ok": True, "msg": "DB Cleared"}

@app.on_event("startup")
def startup(): init_db()