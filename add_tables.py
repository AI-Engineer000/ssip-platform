# Run this ONCE to add new tables to your database
# Command: python add_tables.py

import sqlite3

conn = sqlite3.connect("students.db")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS certifications (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    name     TEXT NOT NULL,
    platform TEXT,
    year     INTEGER,
    link     TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
)""")
c.execute("""
CREATE TABLE IF NOT EXISTS academic_records (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    semester INTEGER NOT NULL,
    sgpa     REAL,
    UNIQUE(user_id, semester),
    FOREIGN KEY(user_id) REFERENCES users(id)
)""")

c.execute("""
CREATE TABLE IF NOT EXISTS student_links (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER UNIQUE NOT NULL,
    linkedin       TEXT,
    github         TEXT,
    leetcode       TEXT,
    portfolio      TEXT,
    about_me       TEXT,
    dream_company  TEXT,
    long_term_goal TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
)""")

conn.commit()
conn.close()
print("✅ Tables created successfully!")
print("   - certifications")
print("   - academic_records")
print("   - student_links")
