import os
import json
import sqlite3
import io
import re
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, jsonify, redirect, session, send_file
from dotenv import load_dotenv
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

_last_ai_call_ts = {}
@app.route('/test-sheets')
def test_sheets():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    email = session['user_email']
    result = find_student_by_email(email)
    
    return jsonify({
        'email': email,
        'found': result is not None,
        'data': result
    })
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


model = genai.GenerativeModel("gemini-2.0-flash")
app = Flask(__name__)
app.secret_key = "ssip_secret_key_2026"

# Database


def init_db():
    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    # TABLE 1: users
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        email      TEXT UNIQUE NOT NULL,
        username   TEXT UNIQUE NOT NULL,
        password   TEXT NOT NULL,
        branch     TEXT,
        semester   INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS student_profile (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id              INTEGER UNIQUE NOT NULL,
        cgpa                 REAL,
        attendance           TEXT,
        backlog              TEXT,
        strong_area          TEXT,
        weak_area            TEXT,
        coding_skill         INTEGER,
        problem_solving      INTEGER,
        communication        INTEGER,
        teamwork             INTEGER,
        project_skill        INTEGER,
        career_goal          TEXT,
        projects_completed   TEXT,
        coding_frequency     TEXT,
        study_hours          TEXT,
        placement_confidence INTEGER,
        technologies         TEXT,
        biggest_challenge    TEXT,
        persona              TEXT,
        success_score        INTEGER,
        placement_readiness  INTEGER,
        academic_risk        TEXT,
        onboarding_done      INTEGER DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

 CREATE TABLE IF NOT EXISTS certifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        platform TEXT,
        year TEXT,
        link TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    
    CREATE TABLE IF NOT EXISTS academic_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        semester INTEGER,
        sgpa REAL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    
    CREATE TABLE IF NOT EXISTS student_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        linkedin TEXT,
        github TEXT,
        leetcode TEXT,
        portfolio TEXT,
        about_me TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)

    conn.commit()
    conn.close()


init_db()


def get_db():
    conn = sqlite3.connect("students.db")
    conn.row_factory = sqlite3.Row
    return conn


def parse_percent(val):
    if val is None:
        return 0
    s = str(val).replace('%', '').strip()
    try:
        return int(float(s))
    except ValueError:
        return 0

# GRADE POINT


def get_grade_point(marks):
    marks = float(marks)
    if marks >= 90:
        return 10
    elif marks >= 80:
        return 9
    elif marks >= 70:
        return 8
    elif marks >= 60:
        return 7
    elif marks >= 50:
        return 6
    elif marks > 40:
        return 5
    elif marks == 40:
        return 4
    else:
        return 0

# saving profile data to database


def save_profile_to_db(profile_data):
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM student_profile WHERE user_id = ?",
        (profile_data["user_id"],)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE student_profile SET
                cgpa=?, attendance=?, backlog=?,
                strong_area=?, weak_area=?,
                coding_skill=?, problem_solving=?, communication=?,
                teamwork=?, project_skill=?,
                career_goal=?, projects_completed=?,
                coding_frequency=?, study_hours=?,
                placement_confidence=?, technologies=?,
                biggest_challenge=?,
                persona=?, success_score=?, placement_readiness=?, academic_risk=?,
                onboarding_done=1
            WHERE user_id=?
        """, (
            profile_data["cgpa"], profile_data["attendance"], profile_data["backlog"],
            profile_data["strong_area"], profile_data["weak_area"],
            profile_data["coding_skill"], profile_data["problem_solving"],
            profile_data["communication"], profile_data["teamwork"],
            profile_data["project_skill"], profile_data["career_goal"],
            profile_data["projects_completed"], profile_data["coding_frequency"],
            profile_data["study_hours"], profile_data["placement_confidence"],
            profile_data["technologies"], profile_data["biggest_challenge"],
            profile_data.get("persona"), profile_data.get("success_score"),
            profile_data.get("placement_readiness"), profile_data.get(
                "academic_risk"),
            profile_data["user_id"]
        ))
    else:
        cols = ", ".join(profile_data.keys())
        placeholders = ", ".join(["?"] * len(profile_data))
        conn.execute(
            f"INSERT INTO student_profile ({cols}) VALUES ({placeholders})",
            list(profile_data.values())
        )

    conn.commit()
    conn.close()

# auth routes


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        branch = request.form.get('branch', '')
        semester = request.form.get('semester', '')

        if not all([name, email, username, password, confirm]):
            return render_template('signup.html', error="All fields are required.")

        if len(name) < 2:
            return render_template('signup.html', error="Name must be at least 2 characters.")

        if '@' not in email or '.' not in email:
            return render_template('signup.html', error="Please enter a valid email address.")

        if len(username) < 3:
            return render_template('signup.html', error="Username must be at least 3 characters.")

        if password != confirm:
            return render_template('signup.html', error="Passwords do not match.")

        if len(password) < 6:
            return render_template('signup.html', error="Password must be at least 6 characters.")

        hashed = generate_password_hash(password)
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users (name, email, username, password, branch, semester) VALUES (?,?,?,?,?,?)",
                (name, email, username, hashed, branch, semester)
            )
            conn.commit()
            conn.close()
            return redirect('/login')
        except sqlite3.IntegrityError as e:
            conn.close()
            if 'email' in str(e):
                return render_template('signup.html', error="Email already registered.")
            return render_template('signup.html', error="Username already taken.")

    return render_template('signup.html')


login_attempts = {}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            
            print(f"Login attempt for username: {username}")
            
            if not username or not password:
                return render_template('login.html', error="Please fill in all fields.")
            
            conn = get_db()
            user = conn.execute(
                "SELECT * FROM users WHERE username = ? OR email = ?",
                (username, username)
            ).fetchone()
            conn.close()
            
            if not user:
                print("User not found")
                return render_template('login.html', error="Invalid username or email.")
            
            if not check_password_hash(user['password'], password):
                print("Invalid password")
                return render_template('login.html', error="Invalid password.")
            
            print(f"Login successful for user: {user['username']}")
            
            session.permanent = True
            session['user'] = user['username']
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['user_email'] = user['email']
            
            # Check if profile exists
            print("Checking profile...")
            conn = get_db()
            profile = conn.execute(
                "SELECT onboarding_done FROM student_profile WHERE user_id=?",
                (user['id'],)
            ).fetchone()
            conn.close()
            
            if profile and profile['onboarding_done'] == 1:
                print("Profile exists, redirecting to dashboard")
                return redirect('/')
            
            # Check Google Sheets
            print("Checking Google Sheets...")
            sheet_row = find_student_by_email(user['email'])
            
            if sheet_row:
                print("Found in Google Sheets, saving profile...")
                profile_data = map_row_to_profile(sheet_row, user['id'])
                save_profile_to_db(profile_data)
                print("Profile saved, redirecting to dashboard")
                return redirect('/')
            
            print("No profile found, redirecting to complete-profile")
            return redirect('/complete-profile')
            
        except Exception as e:
            print(f"ERROR in login: {e}")
            import traceback
            traceback.print_exc()
            return render_template('login.html', error="An error occurred. Please try again.")
    
    return render_template('login.html')
    
@app.before_request
def cleanup_login_attempts():
    """Remove login attempts older than 5 minutes"""
    current_time = datetime.now()
    expired_ips = []
    for ip, (attempts, timestamp) in login_attempts.items():
        if current_time - timestamp > timedelta(minutes=5):
            expired_ips.append(ip)
    for ip in expired_ips:
        login_attempts.pop(ip, None)


@app.route('/complete-profile')
def complete_profile():
    if 'user' not in session:
        return redirect('/login')
    return render_template('complete_profile.html')

# check profile route — checks if the user has a profile in the database or in the Google Sheet


@app.route('/check-profile')
def check_profile():
    if 'user' not in session:
        return redirect('/login')

    sheet_row = find_student_by_email(session['user_email'])

    if sheet_row:
        profile_data = map_row_to_profile(sheet_row, session['user_id'])
        save_profile_to_db(profile_data)
        return redirect('/')

    return redirect('/complete-profile')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# DASHBOARD


@app.route('/')
def home():
    if 'user' not in session:
        return redirect('/login')

    conn = get_db()
    profile = conn.execute(
        "SELECT * FROM student_profile WHERE user_id = ?",
        (session['user_id'],)
    ).fetchone()
    conn.close()

    return render_template('index.html', profile=profile)

# fetch subjects for the given branch and semester


@app.route('/get_subjects', methods=['POST'])
def get_subject():
    data = request.get_json()
    branch = data.get('branch')
    semester = str(data.get('semester'))
    try:
        with open(f"data/{branch}.json") as f:
            subjects_data = json.load(f)
        subjects = subjects_data.get(semester, [])
    except Exception:
        subjects = []
    return jsonify(subjects)

# predict


@app.route('/predict', methods=['POST'])
def predict():
    if 'user' not in session:
        return redirect('/login')

    attendance = float(request.form.get('attendance', 0))
    prevcgpa = request.form.get('prevcgpa')
    branch = request.form.get('branch')
    semester = request.form.get('semester')

    try:
        with open(f"data/{branch}.json") as f:
            subjects_data = json.load(f)
        subjects = subjects_data.get(semester, [])
    except Exception:
        subjects = []

    marks_list = [float(request.form.get(
        f"marks{i}", 0)) for i in range(len(subjects))]

    total, total_credits = 0, 0
    for i, sub in enumerate(subjects):
        gp = get_grade_point(marks_list[i])
        total += gp * sub['credit']
        total_credits += sub['credit']

    sgpa = round(total / total_credits, 2) if total_credits else 0
    prevcgpa = sgpa if not prevcgpa or prevcgpa.strip() == '' else float(prevcgpa)

    subjects_names = [s['name'] for s in subjects]
    predicted, category, weak, suggestions, improved = analyze_student(
        [attendance, prevcgpa, sgpa], subjects_names
    )
    predicted = round(min(predicted, 10), 2)
    improved = round(min(improved, 10), 2)

    conn = get_db()
    profile = conn.execute(
        "SELECT * FROM student_profile WHERE user_id = ?",
        (session['user_id'],)
    ).fetchone()
    conn.close()

    return render_template(
        'index.html',
        profile=profile,
        predicted=predicted, category=category, weak=weak,
        suggestions=suggestions, improved=improved,
        attendance=attendance, prevcgpa=prevcgpa, sgpa=sgpa,
        subjects=subjects, marks=marks_list
    )


# ================================================
# PLACEHOLDER ROUTES
# ================================================
@app.route('/profile')
def profile_page():
    if 'user' not in session:
        return redirect('/login')
    conn = get_db()
    profile = conn.execute(
        "SELECT * FROM student_profile WHERE user_id = ?",
        (session['user_id'],)
    ).fetchone()
    conn.close()
    return render_template('profile.html', profile=profile)


@app.route('/analytics')
def analytics():
    if 'user' not in session:
        return redirect('/login')
    conn = get_db()
    profile = conn.execute(
        "SELECT * FROM student_profile WHERE user_id = ?",
        (session['user_id'],)
    ).fetchone()
    conn.close()
    return render_template('analytics.html', profile=profile)


@app.route('/ai-mentor', methods=['GET', 'POST'])
def ai_mentor():
    if 'user' not in session:
        return redirect('/login')
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM student_profile WHERE user_id = ?",
        (session['user_id'],)
    ).fetchone()
    conn.close()
    profile = dict(row) if row else None
    return render_template('AI_mentor.html', profile=profile)


@app.route('/ai-mentor/chat', methods=['POST'])
def ai_mentor_chat():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    data = request.get_json()
    user_message = data.get('message', '')
    history = data.get('history', [])

    conn = get_db()
    profile = conn.execute(
        "SELECT * FROM student_profile WHERE user_id = ?",
        (session['user_id'],)
    ).fetchone()
    conn.close()

    if not os.getenv("GEMINI_API_KEY"):
        return jsonify({'reply': 'Gemini API key not configured.'}), 500

    try:
        if profile:
            context = f"""You are an AI academic mentor for {session.get('user_name', 'a student')} at MITSGWL.

Student Profile:
- CGPA: {profile['cgpa']}
- Attendance: {profile['attendance']}
- Strong Area: {profile['strong_area']}
- Weak Area: {profile['weak_area']}
- Coding: {profile['coding_skill']}/5
- Problem Solving: {profile['problem_solving']}/5
- Communication: {profile['communication']}/5
- Career Goal: {profile['career_goal']}
- Technologies: {profile['technologies']}
- Success Score: {profile['success_score']}/100
- Placement Readiness: {profile['placement_readiness']} %
- Risk Level: {profile['academic_risk']}

Give personalized, encouraging, honest advice. Keep responses concise(3-5 sentences or bullet points). Reference their data when relevant."""
        else:
            context = "You are a helpful AI academic mentor for engineering students."

        model = genai.GenerativeModel('gemini-2.0-flash')
        chat = model.start_chat()
        response = chat.send_message(f"{context}\n\nStudent: {user_message}")
        return jsonify({'reply': response.text})

    except Exception as e:
        return jsonify({'reply': f'AI temporarily unavailable.'}), 500


@app.route('/study-planner')
def study_planner():
    if 'user' not in session:
        return redirect('/login')
    return render_template('study_planner.html', profile=None)


@app.route('/study-planner/data')
def study_planner_data():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    return jsonify({
        'stats': {'today_total': 0, 'completed': 0, 'pending': 0, 'completion_rate': 0},
        'streak': {'current': 0, 'best': 0},
        'today_tasks': [],
        'upcoming': {'tomorrow': [], 'next_week': []},
        'subjects': [],
        'weekly': []
    })


@app.route('/study-planner/task', methods=['POST'])
def add_task():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    return jsonify({'success': True})


@app.route('/study-planner/task/<int:task_id>', methods=['PUT', 'DELETE'])
def update_task(task_id):
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    return jsonify({'success': True})


@app.route('/study-planner/task/<int:task_id>/complete', methods=['POST'])
def complete_task(task_id):
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    return jsonify({'success': True})


@app.route('/study-planner/generate-ai-plan', methods=['POST'])
def generate_ai_plan():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    return jsonify({'plan': []})


@app.route('/study-planner/apply-ai-plan', methods=['POST'])
def apply_ai_plan():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    return jsonify({'success': True})


@app.route('/placement')
def placement():
    if 'user' not in session:
        return redirect('/login')
    conn = get_db()
    profile = conn.execute(
        "SELECT * FROM student_profile WHERE user_id = ?",
        (session['user_id'],)
    ).fetchone()
    conn.close()
    return render_template('placement.html', profile=profile)


def _safe_int(value, default=0):
    if value is None:
        return default
    try:
        match = re.search(r"\d+", str(value))
        return int(match.group()) if match else default
    except (ValueError, TypeError):
        return default


def _pct_field(profile, field, default=50):
    """A profile column that's already meant to be 0-100."""
    val = profile.get(field)
    if val is None:
        return default
    val = _safe_int(val, default)
    return max(0, min(100, val))


def _coding_frequency_score(profile):
    freq = (profile.get("coding_frequency") or "").strip().lower()
    mapping = {"daily": 90, "weekly": 65, "rarely": 35, "never": 15}
    return mapping.get(freq, 50)


def _placement_confidence_pct(profile):
    val = _safe_int(profile.get("placement_confidence"), 5)
    return val if val > 10 else val * 10


def _projects_completed_count(profile):
    return _safe_int(profile.get("projects_completed"), 0)


def _current_skill_pct(profile, skill_name):
    """Resolve a skill's current % for this student using SKILL_SOURCES."""
    source_type, source_key = SKILL_SOURCES.get(skill_name, ("field", None))
    project_skill = _pct_field(profile, "project_skill", 50)

    if source_type == "field":
        return _pct_field(profile, source_key, 50)

    if source_type == "tech":
        technologies = (profile.get("technologies") or "").lower()
        if source_key in technologies:
            coding_skill = _pct_field(profile, "coding_skill", 50)
            bonus = max(0, (coding_skill - 70) // 5)
            return min(95, 75 + bonus)
        return max(15, round(project_skill * 0.4))

    if source_type == "derived":
        communication = _pct_field(profile, "communication", 50)
        teamwork = _pct_field(profile, "teamwork", 50)
        problem_solving = _pct_field(profile, "problem_solving", 50)
        if source_key == "research":
            return round((problem_solving + communication) / 2)
        if source_key == "business":
            return round((communication + teamwork) / 2)

    return 50


def _skill_gap_for_career(profile, career_key):
    career = CAREER_PATHS[career_key]
    rows = []
    for skill, required in career["required_skills"].items():
        current = _current_skill_pct(profile, skill)
        rows.append({"skill": skill, "current": current, "required": required})
    return rows


def _match_score(profile, career_key):
    career = CAREER_PATHS[career_key]
    skill_scores = []
    for skill, required in career["required_skills"].items():
        current = _current_skill_pct(profile, skill)
        skill_scores.append(
            min(100, round((current / required) * 100)) if required else 100)
    avg_skill_match = sum(skill_scores) / \
        len(skill_scores) if skill_scores else 0

    success_score = _pct_field(profile, "success_score", 50)
    placement_readiness = _pct_field(profile, "placement_readiness", 50)

    match = 0.6 * avg_skill_match + 0.25 * \
        success_score + 0.15 * placement_readiness
    match = round(max(0, min(100, match)))

    if match >= 75:
        confidence = "High"
    elif match >= 50:
        confidence = "Medium"
    else:
        confidence = "Growing"

    return match, confidence


def _career_readiness(profile):
    coding_skill = _pct_field(profile, "coding_skill", 50)
    problem_solving = _pct_field(profile, "problem_solving", 50)
    communication = _pct_field(profile, "communication", 50)
    projects_completed = _projects_completed_count(profile)

    technical_skills = round((coding_skill + problem_solving) / 2)
    projects_pct = round(min(100, (projects_completed / 5) * 100))
    resume_strength = round(
        projects_pct * 0.4 +
        _coding_frequency_score(profile) * 0.3 +
        _placement_confidence_pct(profile) * 0.3
    )

    success_score = _pct_field(profile, "success_score", 50)
    placement_readiness = _pct_field(profile, "placement_readiness", 50)

    overall = round((
        placement_readiness + success_score + technical_skills +
        projects_pct + communication + problem_solving + resume_strength
    ) / 7)

    return {
        "placement_readiness": placement_readiness,
        "technical_skills": technical_skills,
        "projects": projects_pct,
        "communication": communication,
        "problem_solving": problem_solving,
        "resume_strength": resume_strength,
        "overall": overall,
    }


def _missing_skills(profile, career_key, margin=15):
    gap_rows = _skill_gap_for_career(profile, career_key)
    missing = [r["skill"]
               for r in gap_rows if r["required"] - r["current"] >= margin]
    if not missing:
        missing = sorted(
            gap_rows, key=lambda r: r["required"] - r["current"], reverse=True)
        missing = [r["skill"] for r in missing[:3]]
    return missing


def _roadmap(profile, career_key):
    career = CAREER_PATHS[career_key]
    roadmap = []
    for month_label, items in career["roadmap"]:
        steps = []
        for item in items:
            current = _current_skill_pct(
                profile, item) if item in SKILL_SOURCES else None
            if current is not None and current >= 75:
                steps.append(
                    {"text": f"Already solid in {item}", "done": True})
            else:
                steps.append({"text": item, "done": False})
        roadmap.append({"month": month_label, "steps": steps})
    return roadmap


def _current_level(profile, career_key):
    gap_rows = _skill_gap_for_career(profile, career_key)
    avg_current = sum(r["current"] for r in gap_rows) / \
        len(gap_rows) if gap_rows else 50
    if avg_current < 40:
        return "Beginner"
    if avg_current < 70:
        return "Intermediate"
    return "Advanced"


def _best_matches(profile):
    results = []
    for career_key in CAREER_PATHS:
        match, _ = _match_score(profile, career_key)
        results.append({"career": career_key, "match": match})
    results.sort(key=lambda r: r["match"], reverse=True)
    return results[:4]


def _resume_readiness(profile):
    projects_completed = _projects_completed_count(profile)
    recommended = 5
    freq_score = _coding_frequency_score(profile)
    github_activity = "High" if freq_score >= 80 else (
        "Medium" if freq_score >= 50 else "Low")

    readiness = _career_readiness(profile)
    strength_score = readiness["resume_strength"]
    strength_label = "Strong" if strength_score >= 75 else (
        "Moderate" if strength_score >= 45 else "Weak")

    improvements = []
    if projects_completed < recommended:
        improvements.append(
            f"Add {recommended - projects_completed} more Project(s)")
    if github_activity != "High":
        improvements.append("Improve GitHub Activity (commit more regularly)")
    improvements.append("Add Relevant Certifications")
    if _pct_field(profile, "communication", 50) < 60:
        improvements.append("Practice Communication for Interviews")

    return {
        "projects_completed": projects_completed,
        "recommended_projects": recommended,
        "github_activity": github_activity,
        "resume_strength": strength_label,
        "resume_strength_score": strength_score,
        "improvements": improvements,
    }


INTERNSHIP_SITES = [
    {"name": "Internshala", "base": "https://internshala.com/internships/keywords-{q}"},
    {"name": "LinkedIn Jobs", "base": "https://www.linkedin.com/jobs/search/?keywords={q}"},
    {"name": "Indeed", "base": "https://in.indeed.com/jobs?q={q}"},
    {"name": "Naukri", "base": "https://www.naukri.com/{q}-jobs"},
    {"name": "Wellfound", "base": "https://wellfound.com/jobs?query={q}"},
]


def _internship_links(career_key):
    query = CAREER_PATHS[career_key]["internship_query"]
    slug_space = query.replace(" ", "%20")
    slug_dash = query.replace(" ", "-").lower()
    links = []
    for site in INTERNSHIP_SITES:
        if "naukri.com/{q}" in site["base"]:
            url = site["base"].format(q=slug_dash)
        else:
            url = site["base"].format(q=slug_space)
        links.append({"name": site["name"], "url": url})
    return links

# Routes


@app.route('/career')
def career():
    if 'user' not in session:
        return redirect('/login')
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM student_profile WHERE user_id = ?",
        (session['user_id'],)
    ).fetchone()
    conn.close()
    profile = dict(row) if row else None
    return render_template('career.html', profile=profile, career_list=list(CAREER_PATHS.keys()))


@app.route('/career/data')
def career_data_route():
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM student_profile WHERE user_id = ?",
        (session['user_id'],)
    ).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Complete your profile first to unlock Career Path."}), 400

    profile = dict(row)
    career_key = profile.get("career_goal") or "Software Developer"
    if career_key not in CAREER_PATHS:
        career_key = "Software Developer"

    requested_key = request.args.get("career")
    if requested_key in CAREER_PATHS:
        career_key = requested_key

    career = CAREER_PATHS[career_key]
    match, confidence = _match_score(profile, career_key)

    return jsonify({
        "career_key": career_key,
        "career_list": list(CAREER_PATHS.keys()),
        "emoji": career["emoji"],
        "match_score": match,
        "confidence": confidence,
        "based_on": ["Career Goal", "Coding Skill", "Projects Completed", "Success Score", "Technologies Known"],
        "skill_gap": _skill_gap_for_career(profile, career_key),
        "readiness": _career_readiness(profile),
        "missing_skills": _missing_skills(profile, career_key),
        "roadmap": _roadmap(profile, career_key),
        "current_level": _current_level(profile, career_key),
        "certifications": career["certifications"],
        "projects": career["projects"],
        "companies": career["companies"],
        "salary": career["salary"],
        "best_matches": _best_matches(profile),
        "resume_readiness": _resume_readiness(profile),
        "internship_links": _internship_links(career_key),
    })


@app.route('/skills')
def skills_page():
    if 'user' not in session:
        return redirect('/login')
    return render_template('skills.html')


@app.route('/reports')
def reports_page():
    if 'user' not in session:
        return redirect('/login')
    return render_template('reports.html')


@app.route('/skills/data')
def skills_data():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    user_id = session['user_id']
    db = get_db()
    profile = db.execute(
        'SELECT * FROM student_profile WHERE user_id = ?', (user_id,)).fetchone()

    breakdown = {
        'coding_skill': profile['coding_skill'] if profile and profile['coding_skill'] is not None else 0,
        'problem_solving': profile['problem_solving'] if profile and profile['problem_solving'] is not None else 0,
        'communication': profile['communication'] if profile and profile['communication'] is not None else 0,
        'teamwork': profile['teamwork'] if profile and profile['teamwork'] is not None else 0,
        'project_skill': profile['project_skill'] if profile and profile['project_skill'] is not None else 0,
    }
    overall_score = round(sum(breakdown.values()) /
                          len(breakdown)) if profile else 0

    # technologies known (student_profile.technologies, comma separated)
    tech_raw = profile['technologies'] if profile and profile['technologies'] else ''
    technologies = [t.strip() for t in tech_raw.split(',') if t.strip()]

    # growth history — DEMO: no historical snapshots stored yet.
    # Add a skills_history table later (skill values + date) for real data.
    current_coding = breakdown['coding_skill']
    growth_history = {
        'skill_name': 'Coding Skill',
        'labels': ['January', 'February', 'March', 'April'],
        'data': [
            max(current_coding - 30, 0),
            max(current_coding - 20, 0),
            max(current_coding - 10, 0),
            current_coding
        ]
    }

    career_goal = profile['career_goal'] if profile and profile['career_goal'] else 'Not Sure Yet'
    recommendation_map = {
        'AI Engineer': ['SQL', 'Git', 'Machine Learning', 'Deep Learning'],
        'Web Developer': ['React', 'Node.js', 'REST APIs', 'Git'],
        'Data Analyst': ['SQL', 'Excel', 'Power BI', 'Statistics'],
    }
    learn_next = recommendation_map.get(
        career_goal, ['Git', 'SQL', 'DSA', 'Communication'])

    achievements = []
    if breakdown['coding_skill'] >= 50:
        achievements.append({'icon': '🏅', 'title': 'Python Beginner'})
    try:
        proj_count = int(str(profile['projects_completed']).strip(
        )) if profile and profile['projects_completed'] else 0
    except ValueError:
        proj_count = 0
    if proj_count >= 1:
        achievements.append({'icon': '🏅', 'title': 'First Project Completed'})
    if technologies:
        achievements.append({'icon': '🏅', 'title': 'GitHub Profile Created'})
    if profile and profile['study_hours']:
        achievements.append({'icon': '🏅', 'title': '30 Day Streak'})

    weak_skills = [
        {'name': k.replace('_', ' ').title(), 'value': v}
        for k, v in breakdown.items() if v < 50
    ]
    if profile and profile['weak_area']:
        weak_skills.append({'name': profile['weak_area'], 'value': 30})

    db.close()
    return jsonify({
        'overall_score': overall_score,
        'breakdown': breakdown,
        'technologies': technologies,
        'growth_history': growth_history,
        'recommendations': {'goal': career_goal, 'learn_next': learn_next},
        'achievements': achievements,
        'weak_skills': weak_skills
    })


@app.route('/skills/add', methods=['POST'])
def skills_add():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.get_json(silent=True) or {}
    skill_name = (data.get('skill_name') or '').strip()
    level = data.get('level', 'Beginner')
    if not skill_name:
        return jsonify({'success': False, 'error': 'Skill name required'}), 400

    db = get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS user_skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, skill_name TEXT, level TEXT, created_at TEXT
    )''')
    db.execute(
        'INSERT INTO user_skills (user_id, skill_name, level, created_at) VALUES (?, ?, ?, ?)',
        (session['user_id'], skill_name, level,
         datetime.now().strftime('%Y-%m-%d'))
    )
    db.commit()
    db.close()
    return jsonify({'success': True})


@app.route('/reports/data')
def reports_data():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    user_id = session['user_id']
    db = get_db()
    user_row = db.execute(
        'SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    profile = db.execute(
        'SELECT * FROM student_profile WHERE user_id = ?', (user_id,)).fetchone()

    attendance_num = parse_percent(profile['attendance']) if profile else 0

    student_summary = {
        'name': user_row['name'] if user_row else session.get('user_name'),
        'branch': user_row['branch'] if user_row and user_row['branch'] else '–',
        'semester': user_row['semester'] if user_row and user_row['semester'] else '–',
        'cgpa': profile['cgpa'] if profile and profile['cgpa'] is not None else 0,
        'attendance': attendance_num,
        'career_goal': profile['career_goal'] if profile and profile['career_goal'] else 'Not Sure Yet',
    }

    cgpa = student_summary['cgpa'] or 0
    predicted_cgpa = round(min(cgpa + 0.3, 10.0), 1) if cgpa else 0
    risk_level = (profile['academic_risk'] if profile and profile['academic_risk'] else
                  ('Low' if attendance_num >= 75 and cgpa >= 6 else
                   ('Medium' if attendance_num >= 60 else 'High')))
    academic_report = {
        'cgpa': cgpa, 'predicted_cgpa': predicted_cgpa,
        'attendance': attendance_num, 'risk_level': risk_level
    }

    career_report = {
        'career_goal': student_summary['career_goal'],
        'readiness': profile['placement_readiness'] if profile and profile['placement_readiness'] is not None else 0,
        'match_score': profile['success_score'] if profile and profile['success_score'] is not None else 0,
    }

    skills_report = {
        'Coding Skill': profile['coding_skill'] if profile and profile['coding_skill'] is not None else 0,
        'Communication': profile['communication'] if profile and profile['communication'] is not None else 0,
        'Project Skill': profile['project_skill'] if profile and profile['project_skill'] is not None else 0,
    }

    try:
        proj_count = int(str(profile['projects_completed']).strip(
        )) if profile and profile['projects_completed'] else 0
    except ValueError:
        proj_count = 0
    placement_report = {
        'readiness': profile['placement_readiness'] if profile and profile['placement_readiness'] is not None else 0,
        'resume_score': profile['placement_confidence'] if profile and profile['placement_confidence'] is not None else 0,
        'projects_completed': proj_count,
        'certifications': 0,  # ADJUST: add a certifications column/table if you build that feature
    }

    # Study Planner — ADJUST table/column names to match your actual planner table
    task_row = db.execute(
        "SELECT COUNT(*) c FROM sqlite_master WHERE type='table' AND name='study_tasks'"
    ).fetchone()
    if task_row and task_row['c']:
        completed = db.execute(
            "SELECT COUNT(*) c FROM study_tasks WHERE user_id = ? AND status = 'done'", (user_id,)
        ).fetchone()['c']
        pending = db.execute(
            "SELECT COUNT(*) c FROM study_tasks WHERE user_id = ? AND status != 'done'", (user_id,)
        ).fetchone()['c']
        total = completed + pending
        rate = round((completed / total) * 100) if total else 0
    else:
        completed, pending, rate = 0, 0, 0
    study_planner_report = {'tasks_completed': completed,
                            'tasks_pending': pending, 'completion_rate': rate}

    # AI Mentor Insights — ADJUST table/column names to match your chat log table
    insight_row = db.execute(
        "SELECT COUNT(*) c FROM sqlite_master WHERE type='table' AND name='mentor_conversations'"
    ).fetchone()
    if insight_row and insight_row['c']:
        rows = db.execute('''
            SELECT topic, COUNT(*) cnt FROM mentor_conversations
            WHERE user_id = ? GROUP BY topic ORDER BY cnt DESC LIMIT 3
        ''', (user_id,)).fetchall()
        ai_mentor_insights = [
            {'topic': r['topic'], 'count': r['cnt']} for r in rows]
    else:
        ai_mentor_insights = []

    current_score = round(sum([
        skills_report['Coding Skill'], skills_report['Communication'], skills_report['Project Skill']
    ]) / 3) if profile else 0
    performance_trend = {
        'labels': ['January', 'February', 'March', 'April'],
        'data': [
            max(current_score - 20, 0),
            max(current_score - 12, 0),
            max(current_score - 6, 0),
            current_score
        ]
    }

    db.close()
    return jsonify({
        'student_summary': student_summary,
        'academic_report': academic_report,
        'career_report': career_report,
        'skills_report': skills_report,
        'placement_report': placement_report,
        'study_planner_report': study_planner_report,
        'ai_mentor_insights': ai_mentor_insights,
        'performance_trend': performance_trend,
    })


@app.route('/reports/download-pdf')
def reports_download_pdf():
    if 'user' not in session:
        return redirect('/login')

    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    data = reports_data().get_json()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleC', parent=styles['Title'], textColor=colors.HexColor('#7C3AED'))
    heading_style = ParagraphStyle(
        'HeadC', parent=styles['Heading2'], textColor=colors.HexColor('#DC2626'), spaceBefore=14)

    elems = [
        Paragraph('SSIP — Student Performance Report', title_style),
        Spacer(1, 6),
        Paragraph(
            f"Generated on {datetime.now().strftime('%d %b %Y')}", styles['Normal']),
        Spacer(1, 16),
    ]

    def kv_table(title, d):
        elems.append(Paragraph(title, heading_style))
        rows = [[str(k).replace('_', ' ').title(), str(v)]
                for k, v in d.items()]
        t = Table(rows, colWidths=[7*cm, 7*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F0EEFF')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DDDDEE')),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elems.append(t)

    kv_table('Student Summary', data['student_summary'])
    kv_table('Academic Report', data['academic_report'])
    kv_table('Career Report', data['career_report'])
    kv_table('Skills Report', data['skills_report'])
    kv_table('Placement Report', data['placement_report'])
    kv_table('Study Planner Report', data['study_planner_report'])

    doc.build(elems)
    buf.seek(0)
    return send_file(
        buf, mimetype='application/pdf', as_attachment=True,
        download_name=f"SSIP_Report_{session['user']}.pdf"
    )

# error wala seen h


@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

# timeout wala seen


@app.before_request
def check_session_timeout():
    if 'user' in session:
        session.permanent = True
        app.permanent_session_lifetime = timedelta(hours=2)


# RUN
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
