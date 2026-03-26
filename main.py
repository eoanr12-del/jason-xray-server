"""
Jason Seller X-Ray — Backend API Server v2.4 (Data Receiver Mode)
수정 사항: 
1. 서버 직접 크롤링 대신 브라우저 수집 데이터 수신 기능 강화
2. CORS 허용 및 데이터 저장 로직 최적화
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import sqlite3, os, re
from datetime import datetime
from contextlib import contextmanager

app = FastAPI(title="Jason X-Ray API", version="2.4")

# 브라우저 콘솔에서 데이터를 보낼 수 있도록 CORS 전면 허용
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

@app.post("/api/report")
async def report_data(request: Request):
    """브라우저 콘솔에서 수집한 데이터를 서버 DB에 저장"""
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

@app.get("/")
def root(): return {"status": "online", "mode": "receiver"}

@app.on_event("startup")
def startup(): init_db()