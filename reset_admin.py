#!/usr/bin/env python3
"""
Run this from the backend folder to fix admin login:
    python reset_admin.py
"""
import sqlite3, hashlib, uuid

conn = sqlite3.connect("ideathon.db")
c = conn.cursor()

# Create table if it doesn't exist yet
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

admin_hash = hashlib.sha256("admin123".encode()).hexdigest()
existing = c.execute("SELECT id FROM users WHERE email = 'admin@pmrg.com'").fetchone()

if existing:
    c.execute("UPDATE users SET password_hash = ?, is_admin = 1 WHERE email = 'admin@pmrg.com'", (admin_hash,))
    print("✅ Admin password has been reset.")
else:
    admin_id = str(uuid.uuid4())
    c.execute("""INSERT INTO users (id, name, email, phone, organization, password_hash, is_admin)
                 VALUES (?, 'PMRG Admin', 'admin@pmrg.com', '0000000000', 'PMRG Solution', ?, 1)""",
              (admin_id, admin_hash))
    print("✅ Admin account created.")

conn.commit()
conn.close()

print("")
print("   Email:    admin@pmrg.com")
print("   Password: admin123")
print("")
print("Now restart main.py and try logging in again.")