from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, timedelta
import sqlite3
import json
import uuid
import os
import shutil
import jwt
import hashlib
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="PMRG Ideathon Portal", version="1.0.0")

FRONTEND_ORIGINS = os.getenv(
    "FRONTEND_ORIGINS",
    "http://localhost:3000,http://localhost:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    # Old local-only origins:
    # allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def resolve_app_path(path: str):
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)

# Old relative upload path:
# UPLOAD_DIR = "uploads"
UPLOAD_DIR = resolve_app_path(os.getenv("UPLOAD_DIR", "uploads"))
DB_PATH = resolve_app_path(os.getenv("DB_PATH", "ideathon.db"))
os.makedirs(UPLOAD_DIR, exist_ok=True)
# Old hardcoded secret:
# SECRET_KEY = "pmrg-ideathon-secret-2024"
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
ALGORITHM = "HS256"

# ─── Database Setup ───────────────────────────────────────────────────────────

def get_db():
    # Old relative DB path:
    # conn = sqlite3.connect("ideathon.db")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    # Old relative DB path:
    # conn = sqlite3.connect("ideathon.db")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT NOT NULL,
        organization TEXT,
        internship_id TEXT,
        department TEXT,
        linkedin TEXT,
        password_hash TEXT,
        is_admin INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS ideas (
        id TEXT PRIMARY KEY,
        submission_id TEXT UNIQUE NOT NULL,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        problem_statement TEXT NOT NULL,
        proposed_solution TEXT NOT NULL,
        category TEXT NOT NULL,
        idea_summary TEXT NOT NULL,
        target_audience TEXT NOT NULL,
        market_opportunity TEXT,
        competitive_advantage TEXT,
        revenue_model TEXT,
        current_stage TEXT NOT NULL,
        business_impact TEXT,
        scalability TEXT,
        tech_requirements TEXT,
        figma_link TEXT,
        github_link TEXT,
        drive_link TEXT,
        demo_url TEXT,
        status TEXT DEFAULT 'Under Review',
        evaluation_score REAL,
        reviewer_notes TEXT,
        submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS attachments (
        id TEXT PRIMARY KEY,
        idea_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        original_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_size INTEGER,
        uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (idea_id) REFERENCES ideas(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS evaluations (
        id TEXT PRIMARY KEY,
        idea_id TEXT NOT NULL,
        reviewer_id TEXT,
        innovation_score INTEGER,
        feasibility_score INTEGER,
        market_score INTEGER,
        scalability_score INTEGER,
        comments TEXT,
        evaluated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (idea_id) REFERENCES ideas(id)
    )""")

    # Default admin account
    admin_id = str(uuid.uuid4())
    admin_hash = hashlib.sha256("admin123".encode()).hexdigest()
    c.execute("""INSERT OR IGNORE INTO users (id, name, email, phone, organization, password_hash, is_admin)
                 VALUES (?, 'PMRG Admin', 'admin@pmrg.com', '0000000000', 'PMRG Solution', ?, 1)""",
              (admin_id, admin_hash))

    conn.commit()
    conn.close()

init_db()

# ─── Auth Helpers ─────────────────────────────────────────────────────────────

security = HTTPBearer(auto_error=False)

def create_token(user_id: str, is_admin: bool):
    payload = {"sub": user_id, "is_admin": is_admin, "exp": datetime.utcnow() + timedelta(days=7)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: sqlite3.Connection = Depends(get_db)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return dict(user)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_admin(user=Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# ─── Models ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    phone: str
    organization: Optional[str] = None
    internship_id: Optional[str] = None
    department: Optional[str] = None
    linkedin: Optional[str] = None
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class IdeaRequest(BaseModel):
    title: str
    problem_statement: str
    proposed_solution: str
    category: str
    idea_summary: str
    target_audience: str
    market_opportunity: Optional[str] = None
    competitive_advantage: Optional[str] = None
    revenue_model: Optional[str] = None
    current_stage: str
    business_impact: Optional[str] = None
    scalability: Optional[str] = None
    tech_requirements: Optional[str] = None
    figma_link: Optional[str] = None
    github_link: Optional[str] = None
    drive_link: Optional[str] = None
    demo_url: Optional[str] = None

class EvaluationRequest(BaseModel):
    innovation_score: int
    feasibility_score: int
    market_score: int
    scalability_score: int
    comments: Optional[str] = None

class StatusUpdateRequest(BaseModel):
    status: str

# ─── Auth Routes ──────────────────────────────────────────────────────────────

@app.post("/api/auth/register")
def register(req: RegisterRequest, db: sqlite3.Connection = Depends(get_db)):
    existing = db.execute("SELECT id FROM users WHERE email = ?", (req.email,)).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user_id = str(uuid.uuid4())
    password_hash = hashlib.sha256(req.password.encode()).hexdigest()

    db.execute("""INSERT INTO users (id, name, email, phone, organization, internship_id, department, linkedin, password_hash)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
               (user_id, req.name, req.email, req.phone, req.organization,
                req.internship_id, req.department, req.linkedin, password_hash))
    db.commit()

    token = create_token(user_id, False)
    return {"token": token, "user": {"id": user_id, "name": req.name, "email": req.email, "is_admin": False}}

@app.post("/api/auth/login")
def login(req: LoginRequest, db: sqlite3.Connection = Depends(get_db)):
    password_hash = hashlib.sha256(req.password.encode()).hexdigest()
    user = db.execute("SELECT * FROM users WHERE email = ? AND password_hash = ?",
                      (req.email, password_hash)).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = dict(user)
    token = create_token(user["id"], bool(user["is_admin"]))
    return {"token": token, "user": {"id": user["id"], "name": user["name"],
                                      "email": user["email"], "is_admin": bool(user["is_admin"])}}

@app.get("/api/auth/me")
def me(user=Depends(get_current_user)):
    return {"id": user["id"], "name": user["name"], "email": user["email"],
            "organization": user.get("organization"), "department": user.get("department"),
            "is_admin": bool(user["is_admin"])}

# ─── Idea Routes ──────────────────────────────────────────────────────────────

@app.post("/api/ideas")
def submit_idea(req: IdeaRequest, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    idea_id = str(uuid.uuid4())
    count = db.execute("SELECT COUNT(*) as c FROM ideas").fetchone()["c"] + 1
    submission_id = f"IDEA-{count:04d}"

    db.execute("""INSERT INTO ideas (id, submission_id, user_id, title, problem_statement, proposed_solution,
        category, idea_summary, target_audience, market_opportunity, competitive_advantage, revenue_model,
        current_stage, business_impact, scalability, tech_requirements, figma_link, github_link, drive_link, demo_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
               (idea_id, submission_id, user["id"], req.title, req.problem_statement, req.proposed_solution,
                req.category, req.idea_summary, req.target_audience, req.market_opportunity,
                req.competitive_advantage, req.revenue_model, req.current_stage, req.business_impact,
                req.scalability, req.tech_requirements, req.figma_link, req.github_link,
                req.drive_link, req.demo_url))
    db.commit()

    return {"idea_id": idea_id, "submission_id": submission_id, "status": "Under Review",
            "submitted_at": datetime.utcnow().isoformat()}

@app.get("/api/ideas/my")
def my_ideas(user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    ideas = db.execute("""SELECT i.*, u.name as submitter_name FROM ideas i
                          JOIN users u ON u.id = i.user_id
                          WHERE i.user_id = ? ORDER BY i.submitted_at DESC""",
                       (user["id"],)).fetchall()
    return [dict(i) for i in ideas]

@app.get("/api/ideas/{idea_id}")
def get_idea(idea_id: str, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    idea = db.execute("""SELECT i.*, u.name as submitter_name, u.email as submitter_email
                         FROM ideas i JOIN users u ON u.id = i.user_id WHERE i.id = ?""",
                      (idea_id,)).fetchone()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    idea = dict(idea)
    if idea["user_id"] != user["id"] and not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Access denied")
    attachments = db.execute("SELECT * FROM attachments WHERE idea_id = ?", (idea_id,)).fetchall()
    idea["attachments"] = [dict(a) for a in attachments]
    return idea

@app.post("/api/ideas/{idea_id}/attachments")
async def upload_attachment(idea_id: str, file: UploadFile = File(...),
                             user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    idea = db.execute("SELECT * FROM ideas WHERE id = ? AND user_id = ?", (idea_id, user["id"])).fetchone()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found or access denied")

    if file.size and file.size > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 25MB)")

    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    filename = f"{file_id}{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = os.path.getsize(file_path)
    db.execute("""INSERT INTO attachments (id, idea_id, filename, original_name, file_path, file_size)
                  VALUES (?, ?, ?, ?, ?, ?)""",
               (file_id, idea_id, filename, file.filename, file_path, file_size))
    db.commit()

    return {"id": file_id, "original_name": file.filename, "file_size": file_size}

# ─── Admin Routes ─────────────────────────────────────────────────────────────

@app.get("/api/admin/stats")
def admin_stats(admin=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    total_users = db.execute("SELECT COUNT(*) as c FROM users WHERE is_admin = 0").fetchone()["c"]
    total_ideas = db.execute("SELECT COUNT(*) as c FROM ideas").fetchone()["c"]
    shortlisted = db.execute("SELECT COUNT(*) as c FROM ideas WHERE status = 'Shortlisted'").fetchone()["c"]
    under_review = db.execute("SELECT COUNT(*) as c FROM ideas WHERE status = 'Under Review'").fetchone()["c"]
    selected = db.execute("SELECT COUNT(*) as c FROM ideas WHERE status = 'Selected'").fetchone()["c"]
    by_category = db.execute("""SELECT category, COUNT(*) as count FROM ideas GROUP BY category""").fetchall()
    return {
        "total_participants": total_users, "total_ideas": total_ideas,
        "shortlisted": shortlisted, "under_review": under_review,
        "selected": selected, "by_category": [dict(r) for r in by_category]
    }

@app.get("/api/admin/ideas")
def admin_ideas(status: Optional[str] = None, category: Optional[str] = None,
                search: Optional[str] = None, admin=Depends(require_admin),
                db: sqlite3.Connection = Depends(get_db)):
    query = """SELECT i.*, u.name as submitter_name, u.email as submitter_email,
                      u.organization, u.department FROM ideas i JOIN users u ON u.id = i.user_id WHERE 1=1"""
    params = []
    if status:
        query += " AND i.status = ?"
        params.append(status)
    if category:
        query += " AND i.category = ?"
        params.append(category)
    if search:
        query += " AND (i.title LIKE ? OR u.name LIKE ? OR i.submission_id LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    query += " ORDER BY i.submitted_at DESC"
    ideas = db.execute(query, params).fetchall()
    return [dict(i) for i in ideas]

@app.put("/api/admin/ideas/{idea_id}/status")
def update_status(idea_id: str, req: StatusUpdateRequest, admin=Depends(require_admin),
                  db: sqlite3.Connection = Depends(get_db)):
    valid_statuses = ["Submitted", "Under Review", "Shortlisted", "Interview Scheduled",
                      "Selected", "Incubation Phase", "Closed"]
    if req.status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")
    db.execute("UPDATE ideas SET status = ? WHERE id = ?", (req.status, idea_id))
    db.commit()
    return {"success": True, "status": req.status}

@app.post("/api/admin/ideas/{idea_id}/evaluate")
def evaluate_idea(idea_id: str, req: EvaluationRequest, admin=Depends(require_admin),
                  db: sqlite3.Connection = Depends(get_db)):
    eval_id = str(uuid.uuid4())
    avg_score = (req.innovation_score + req.feasibility_score + req.market_score + req.scalability_score) / 4

    db.execute("""INSERT INTO evaluations (id, idea_id, reviewer_id, innovation_score, feasibility_score,
                  market_score, scalability_score, comments) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
               (eval_id, idea_id, admin["id"], req.innovation_score, req.feasibility_score,
                req.market_score, req.scalability_score, req.comments))
    db.execute("UPDATE ideas SET evaluation_score = ?, reviewer_notes = ? WHERE id = ?",
               (avg_score, req.comments, idea_id))
    db.commit()
    return {"success": True, "average_score": avg_score}

@app.get("/api/admin/ideas/{idea_id}")
def admin_get_idea(idea_id: str, admin=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    idea = db.execute("""SELECT i.*, u.name as submitter_name, u.email as submitter_email,
                         u.phone as submitter_phone, u.organization, u.department, u.linkedin
                         FROM ideas i JOIN users u ON u.id = i.user_id WHERE i.id = ?""",
                      (idea_id,)).fetchone()
    if not idea:
        raise HTTPException(status_code=404, detail="Not found")
    idea = dict(idea)
    attachments = db.execute("SELECT * FROM attachments WHERE idea_id = ?", (idea_id,)).fetchall()
    evaluations = db.execute("SELECT * FROM evaluations WHERE idea_id = ?", (idea_id,)).fetchall()
    idea["attachments"] = [dict(a) for a in attachments]
    idea["evaluations"] = [dict(e) for e in evaluations]
    return idea

if __name__ == "__main__":
    import uvicorn
    # Old fixed port:
    # uvicorn.run(app, host="0.0.0.0", port=8000)
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
