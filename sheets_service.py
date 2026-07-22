import os
import json
import base64
import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = "1Z7DK3kCkJEX-P-ddOD4e7_szK-iPADSpFEHi2wP9lN4"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly"
]

def get_sheet():
    try:
        creds_b64 = os.getenv("GOOGLE_CREDENTIALS")
        
        if creds_b64:
            creds_data = base64.b64decode(creds_b64).decode('utf-8')
            creds_dict = json.loads(creds_data)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        else:
            with open("credentials.json", "r") as f:
                creds_dict = json.load(f)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        return sheet
    except Exception as e:
        print(f"Failed to connect to Google Sheets: {e}")
        raise

def find_student_by_email(email):
    try:
        sheet = get_sheet()
        records = sheet.get_all_records()
        email = email.strip().lower()
        
        print(f"Looking for email: {email}")
        print(f"Total records: {len(records)}")
        
        if records:
            print("Column names in sheet:", list(records[0].keys()))
        
        for idx, row in enumerate(records):
            # Check both email columns
            email1 = str(row.get("Email Address", "")).strip().lower()
            email2 = str(row.get("College Email ID", "")).strip().lower()
            
            if email1 == email or email2 == email:
                print(f"Found student at row {idx+2}")
                return row
        
        print("Student not found in sheet")
        return None
    except Exception as e:
        print(f"[Sheets Error] {e}")
        import traceback
        traceback.print_exc()
        return None

def map_row_to_profile(row, user_id):
    def safe_int(val, default=0):
        try:
            return int(str(val).strip())
        except:
            return default
    
    def safe_float(val, default=0.0):
        try:
            return float(str(val).strip())
        except:
            return default
    
    def safe_str(val, default=""):
        try:
            return str(val).strip()
        except:
            return default
    
    # Map all fields with exact column names from your form
    coding_skill = safe_int(row.get("Rate your coding / technical skills.  ", 0))
    problem_solving = safe_int(row.get("Rate your problem-solving ability.  ", 0))
    communication = safe_int(row.get("Rate your communication skills.", 0))
    teamwork = safe_int(row.get("Rate your Teamwork & Collaboration Skills", 0))
    project_skill = safe_int(row.get("Rate your project-building / practical implementation skills.    ", 0))
    placement_conf = safe_int(row.get("How confident are you about your placement/career preparation?  ", 0))
    
    cgpa = safe_float(row.get("Current CGPA", 0.0))
    attendance = safe_str(row.get("Overall Attendance %", ""))
    backlog = safe_str(row.get("Have you ever received a backlog in any subject?  ", "No"))
    strong_area = safe_str(row.get("Which academic area do you perform best in? ", ""))
    weak_area = safe_str(row.get("Which academic area do you find most challenging?", ""))
    career_goal = safe_str(row.get("Which career path interests you the most?    ", ""))
    projects = safe_str(row.get("How many projects have you completed so far?    ", "0"))
    code_freq = safe_str(row.get("How often do you practice coding?     ", ""))
    study_hrs = safe_str(row.get("On average, how many hours do you study per day?  ", ""))
    technologies = safe_str(row.get("Which technologies are you currently learning?", ""))
    challenge = safe_str(row.get("What is your biggest challenge right now?  ", ""))
    
    # Calculate scores
    cgpa_score = (cgpa / 10) * 40
    att_map = {"95-100%": 25, "85-94%": 22, "75-84%": 18, "60-74%": 12, "Below 60%": 5}
    att_score = att_map.get(attendance, 15)
    freq_map = {"Daily": 20, "3-5 Times a Week": 17, "3–5 Times a Week": 17, "1-2 Times a Week": 12, "1–2 Times a Week": 12, "Rarely": 6, "Never": 0}
    consistency_score = freq_map.get(code_freq, 10)
    avg_skill = (coding_skill + problem_solving + project_skill) / 3
    skill_score = (avg_skill / 5) * 15
    backlog_penalty = 10 if backlog == "Yes" else (4 if backlog == "Maybe" else 0)
    
    success_score = max(0, min(100, int(cgpa_score + att_score + consistency_score + skill_score - backlog_penalty)))
    
    tech_score = ((coding_skill + problem_solving + project_skill) / 15) * 35
    proj_map = {"0": 0, "1-2": 15, "1–2": 15, "3-5": 22, "3–5": 22, "6-10": 25, "6–10": 25, "More than 10": 25}
    proj_score = proj_map.get(projects, 10)
    comm_score = (communication / 5) * 20
    cons_score2 = (consistency_score / 20) * 20
    placement_readiness = max(0, min(100, int(tech_score + proj_score + comm_score + cons_score2)))
    
    if cgpa < 6.0 or attendance in ["Below 60%", "60-74%"] or backlog == "Yes":
        academic_risk = "High"
    elif cgpa < 7.5 or attendance == "75-84%":
        academic_risk = "Medium"
    else:
        academic_risk = "Low"
    
    if coding_skill >= 4 and projects in ["3–5", "3-5", "6–10", "6-10", "More than 10"]:
        persona = "The Builder"
    elif cgpa >= 8.5 and attendance in ["85-94%", "95-100%"]:
        persona = "Academic Achiever"
    elif "Research" in career_goal or "AI" in career_goal:
        persona = "Research Explorer"
    elif placement_conf >= 4:
        persona = "Career-Focused Learner"
    else:
        persona = "Balanced Learner"
    
    print(f"Profile created for user {user_id}: CGPA={cgpa}, Success={success_score}, Risk={academic_risk}")
    
    return {
        "user_id": user_id,
        "cgpa": cgpa,
        "attendance": attendance,
        "backlog": backlog,
        "strong_area": strong_area,
        "weak_area": weak_area,
        "coding_skill": coding_skill,
        "problem_solving": problem_solving,
        "communication": communication,
        "teamwork": teamwork,
        "project_skill": project_skill,
        "career_goal": career_goal,
        "projects_completed": projects,
        "coding_frequency": code_freq,
        "study_hours": study_hrs,
        "placement_confidence": placement_conf,
        "technologies": technologies,
        "biggest_challenge": challenge,
        "persona": persona,
        "success_score": success_score,
        "placement_readiness": placement_readiness,
        "academic_risk": academic_risk,
        "onboarding_done": 1
    }
