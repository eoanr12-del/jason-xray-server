"""
Jason Seller X-Ray — Backend API Server v2.6 (Full Compatibility)
수정 사항: 
1. 외부 프로그램용 조회 경로 (/api/product/{pid}) 추가
2. 데이터 저장 및 전체 조회 유지
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import sqlite3, os
from datetime import datetime
from contextlib import contextmanager

app = FastAPI(title="Jason X-Ray API", version="2.6")

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
        conn.execute("CREATE TABLE IF NOT EXISTS products (pid TEXT PRIMARY KEY, name TEXT, price INTEGER, updated_at TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS stock_history (pid TEXT, stock INTEGER, price INTEGER, recorded_at TEXT)")
        conn.commit()

@app.get("/")
def root(): 
    return {"status": "online", "mode": "full-compatibility"}

# [추가] 스크린샷의 404 에러를 해결하는 개별 상품 조회 경로
@app.get("/api/product/{pid}")
async def get_product(pid: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM products WHERE pid = ?", (pid,)).fetchone()
    if not row:
        # 데이터가 없어도 에러 대신 빈 객체를 주어 프로그램이 멈추지 않게 합니다.
        return {"ok": False, "msg": "No data yet"}
    return {"ok": True, "data": dict(row)}

# 전체 데이터 확인용
@app.get("/api/report")
async def get_all_data():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY updated_at DESC").fetchall()
    return {"ok": True, "count": len(rows), "data": [dict(r) for r in rows]}

# 데이터 저장용
@app.post("/api/report")
async def report_data(request: Request):
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
        return {"ok": True, "pid": pid}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

@app.on_event("startup")
def startup(): init_db()