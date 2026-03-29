import json
import os
import re
import zipfile
from collections import Counter
from datetime import datetime
from functools import wraps
from pathlib import Path

import matplotlib
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from db import close_db, db_commit, db_execute, db_fetchall, db_fetchone, initialize_database, next_id

matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    import openai
except ImportError:  # pragma: no cover - optional dependency
    openai = None

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"
ALLOWED_EXTENSIONS = {"docx"}
FEATHERLESS_API_KEY = os.getenv("FEATHERLESS_API_KEY", "rc_ad6ea9a9354ea7b4186efbc0ccf295ccf6af1fcf6a406a58bc8cea0b37203e3e").strip()
FEATHERLESS_MODEL = os.getenv("FEATHERLESS_MODEL", "meta-llama/Meta-Llama-3.1-70B-Instruct")

SKILL_CATALOG = {
    "python",
    "java",
    "c++",
    "c#",
    "sql",
    "mysql",
    "postgresql",
    "mongodb",
    "flask",
    "django",
    "fastapi",
    "html",
    "css",
    "javascript",
    "typescript",
    "react",
    "node.js",
    "node",
    "pandas",
    "numpy",
    "machine learning",
    "deep learning",
    "nlp",
    "data analysis",
    "data visualization",
    "matplotlib",
    "power bi",
    "tableau",
    "excel",
    "git",
    "github",
    "docker",
    "kubernetes",
    "aws",
    "azure",
    "gcp",
    "linux",
    "rest api",
    "api",
    "scikit-learn",
    "tensorflow",
    "pytorch",
    "communication",
    "leadership",
    "problem solving",
    "project management",
}

EDUCATION_RANK = {
    "high_school": 1,
    "diploma": 2,
    "bachelor": 3,
    "master": 4,
    "phd": 5,
}

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = str(UPLOAD_DIR)

app.teardown_appcontext(close_db)


@app.before_request
def ensure_database():
    UPLOAD_DIR.mkdir(exist_ok=True)
    STATIC_DIR.mkdir(exist_ok=True)
    initialize_database()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("role") != role:
                flash("Please log in with the correct account.", "error")
                target = "admin_login" if role == "admin" else "candidate_login"
                return redirect(url_for(target))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def tokenize(text):
    return re.findall(r"[a-z0-9+#.]+", text.lower())


def extract_resume_text(docx_path):
    with zipfile.ZipFile(docx_path) as archive:
        xml_content = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    text = re.sub(r"</w:p>", "\n", xml_content)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_email(text):
    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return match.group(0) if match else ""


def extract_phone(text):
    match = re.search(r"(\+?\d[\d\-\s]{8,}\d)", text)
    return match.group(0).strip() if match else ""


def extract_candidate_name(text):
    parts = [part.strip() for part in re.split(r"[\r\n]+", text) if part.strip()]
    for part in parts[:8]:
        cleaned = re.sub(r"[^A-Za-z\s]", "", part).strip()
        if len(cleaned.split()) in (2, 3):
            return cleaned.title()
    return ""


def extract_skills(text):
    lowered = text.lower()
    found = set()
    for skill in SKILL_CATALOG:
        if re.search(rf"(?<!\w){re.escape(skill.lower())}(?!\w)", lowered):
            found.add(skill)
    return sorted(found)


def extract_experience_years(text):
    lowered = text.lower()
    explicit = re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)[^.\n]{0,20}experience", lowered)
    if explicit:
        return max(float(value) for value in explicit)

    ranges = re.findall(r"(20\d{2})\s*[-]\s*(20\d{2}|present|current)", lowered)
    current_year = datetime.utcnow().year
    totals = []
    for start, end in ranges:
        end_year = current_year if end in {"present", "current"} else int(end)
        totals.append(max(0, end_year - int(start)))
    return float(max(totals)) if totals else 0.0


def extract_education_level(text):
    lowered = text.lower()
    if any(token in lowered for token in ("phd", "doctor of philosophy", "doctorate")):
        return "phd"
    if any(token in lowered for token in ("master", "mba", "m.tech", "mtech", "msc", "ms ")):
        return "master"
    if any(token in lowered for token in ("bachelor", "b.tech", "btech", "b.e", "bsc", "bs ")):
        return "bachelor"
    if "diploma" in lowered:
        return "diploma"
    return "high_school"


def education_requirement_level(requirements_text):
    lowered = requirements_text.lower()
    if "phd" in lowered:
        return "phd"
    if any(token in lowered for token in ("master", "mba", "m.tech", "mtech")):
        return "master"
    if any(token in lowered for token in ("bachelor", "graduate", "degree", "b.tech", "btech")):
        return "bachelor"
    return "high_school"


def extract_required_skills(requirements_text):
    lowered = requirements_text.lower()
    found = set()
    for skill in SKILL_CATALOG:
        if re.search(rf"(?<!\w){re.escape(skill.lower())}(?!\w)", lowered):
            found.add(skill)
    return sorted(found)


def compute_keyword_score(requirements_text, resume_text):
    stop_words = {
        "the", "and", "with", "for", "this", "that", "you", "are", "our", "your",
        "from", "have", "has", "will", "able", "into", "their", "role", "job",
        "candidate", "should", "strong", "understand", "years",
    }
    requirement_tokens = [token for token in tokenize(requirements_text) if len(token) > 2 and token not in stop_words]
    resume_tokens = set(tokenize(resume_text))
    if not requirement_tokens:
        return 0.0
    matched = sum(1 for token in requirement_tokens if token in resume_tokens)
    return (matched / len(requirement_tokens)) * 100


def compute_completeness_score(parsed):
    checks = [
        bool(parsed["name"]),
        bool(parsed["email"]),
        bool(parsed["phone"]),
        bool(parsed["skills"]),
        parsed["experience_years"] > 0,
        parsed["education_level"] != "high_school",
    ]
    return (sum(checks) / len(checks)) * 100


def assess_resume_quality(resume_text, parsed):
    lowered = resume_text.lower()
    tokens = tokenize(resume_text)
    unique_tokens = set(tokens)
    section_hits = sum(
        1
        for section in ("experience", "education", "skills", "projects", "employment", "summary")
        if section in lowered
    )
    blocking_issues = []
    warnings = []

    if len(resume_text.strip()) < 80:
        blocking_issues.append("Resume content is too short to evaluate reliably.")
    elif len(resume_text.strip()) < 180:
        warnings.append("Resume content is quite short, so the score may be conservative.")

    if len(unique_tokens) < 12:
        blocking_issues.append("Resume does not contain enough unique information.")
    elif len(unique_tokens) < 24:
        warnings.append("Resume contains limited unique information.")

    if not parsed["email"] and not parsed["phone"]:
        blocking_issues.append("Resume is missing contact details.")
    elif not parsed["email"] or not parsed["phone"]:
        warnings.append("Resume is missing one important contact detail.")

    if section_hits < 1:
        blocking_issues.append("Resume is missing standard resume sections such as skills, education, or experience.")
    elif section_hits < 2:
        warnings.append("Resume structure is limited and may not reflect the full profile.")

    if len(tokens) > 0 and (len(tokens) - len(unique_tokens)) / len(tokens) > 0.7:
        blocking_issues.append("Resume content appears repetitive or low quality.")
    elif len(tokens) > 0 and (len(tokens) - len(unique_tokens)) / len(tokens) > 0.55:
        warnings.append("Resume has repeated wording that reduces confidence.")

    quality_score = 100.0
    if len(resume_text.strip()) < 220:
        quality_score -= 20
    if len(unique_tokens) < 24:
        quality_score -= 20
    if not parsed["email"]:
        quality_score -= 10
    if not parsed["phone"]:
        quality_score -= 10
    if section_hits < 2:
        quality_score -= 20
    quality_score = max(0.0, quality_score)

    return {
        "is_valid": len(blocking_issues) == 0,
        "quality_score": round(quality_score, 2),
        "issues": blocking_issues,
        "warnings": warnings,
    }


def normalize_parameter_scores(parameter_scores):
    normalized = []
    for item in parameter_scores or []:
        name = str(item.get("name", "")).strip() or "Unnamed"
        group = str(item.get("group", "core")).strip() or "core"
        score = max(0.0, min(100.0, float(item.get("score", 0) or 0)))
        priority = int(item.get("priority", 3) or 3)
        evidence = str(item.get("evidence", "") or "").strip()
        normalized.append(
            {
                "name": name,
                "group": group,
                "score": round(score, 2),
                "priority": max(1, min(priority, 5)),
                "evidence": evidence,
            }
        )
    return normalized


def weighted_parameter_score(parameter_scores):
    if not parameter_scores:
        return 0.0
    total_weight = sum(item["priority"] for item in parameter_scores)
    if total_weight == 0:
        return 0.0
    weighted_sum = sum(item["score"] * item["priority"] for item in parameter_scores)
    return round(weighted_sum / total_weight, 2)


def normalize_finding_items(items):
    normalized = []
    for item in items or []:
        if isinstance(item, str):
            text = item.strip()
            priority = 3
        else:
            text = str(item.get("text", "") or "").strip()
            priority = int(item.get("priority", 3) or 3)
        if text:
            normalized.append({"text": text, "priority": max(1, min(priority, 5))})
    return normalized


def finalize_decision(analysis, job):
    status = str(analysis.get("recommendation_status", "Review") or "Review").title()
    if status not in {"Rejected", "Review", "Shortlisted"}:
        status = "Review"
    rejection_reasons = list(analysis.get("candidate_missing", []))
    rejection_reasons = [item["text"] if isinstance(item, dict) else str(item) for item in rejection_reasons]
    rejection_reasons.extend(item["text"] for item in analysis.get("blindspots", []) if item["priority"] >= 4)
    if status == "Rejected" and not rejection_reasons:
        rejection_reasons.append("The resume is not a strong enough match for the selected role.")

    fit_label = {
        "Rejected": "Not Suitable",
        "Review": "Needs Review",
        "Shortlisted": "Strong Match",
    }[status]

    analysis["status"] = status
    analysis["fit_label"] = fit_label
    analysis["rejection_reasons"] = rejection_reasons
    analysis["is_useful_resume"] = status != "Rejected"
    analysis["summary"]["fit_label"] = fit_label
    analysis["summary"]["rejection_reasons"] = rejection_reasons
    analysis["summary"]["job_title"] = job["title"]
    analysis["summary"]["job_summary"] = job.get("summary", "")
    analysis["summary"]["job_requirement_alignment"] = analysis.get("job_requirement_alignment", "")
    analysis["summary"]["resume_evidence_summary"] = analysis.get("resume_evidence_summary", "")
    analysis["summary"]["final_decision_reason"] = analysis.get("final_decision_reason", "")
    analysis["summary"]["ranking_basis"] = analysis.get("ranking_basis", "")
    return analysis


def build_llm_client():
    if not FEATHERLESS_API_KEY or openai is None:
        return None
    return openai.OpenAI(base_url="https://api.featherless.ai/v1", api_key=FEATHERLESS_API_KEY)


def featherless_resume_analysis(candidate, job, resume_text):
    client = build_llm_client()
    if client is None:
        return None

    prompt = f"""
You are analyzing a candidate resume for a job application.
Return strict JSON only.

Candidate profile:
Name: {candidate["name"]}
Email: {candidate["email"]}
Phone: {candidate["phone"]}

Job title: {job["title"]}
Department: {job["department"]}
Location: {job["location"]}
Employment type: {job["employment_type"]}
Job summary: {job["summary"]}
Role overview: {job["role_overview"]}
Responsibilities: {job["responsibilities_text"]}
Core requirements: {job["requirements_text"]}
Qualifications: {job["qualifications_text"]}
Preferred qualifications: {job["preferred_text"]}
Minimum experience: {job["min_experience"]}

Resume text:
{resume_text[:12000]}

Resume content should be weighted more heavily than any candidate note. Judge the resume text itself first.
If the document is weak, irrelevant, shallow, inconsistent, or missing critical signals, say so clearly.

Focus strongly on:
- expertise depth
- project complexity
- achievements
- role relevance
- consistency
- risks
- blindspots
- CGPA or academic quality when present
- what the candidate has
- what the candidate lacks
- clear ranking basis for comparison against other applicants for the same job

The final decision must be based on the selected job requirements plus the actual resume content.
Use the resume text as the primary evidence source and explicitly compare it with the job requirements, qualifications, responsibilities, and minimum experience.
Do not give a generic answer. The output must explain why this resume does or does not fit this specific job.

Required JSON format:
{{
  "extracted_name": "string",
  "extracted_email": "string",
  "extracted_phone": "string",
  "skills": ["skill1", "skill2"],
  "matched_skills": ["skill1"],
  "keywords_found": ["python", "flask"],
  "projects": ["project summary"],
  "achievements": ["achievement summary"],
  "cgpa": "8.6/10 or blank",
  "experience_years": 0,
  "education_level": "high_school|diploma|bachelor|master|phd",
  "parameter_scores": [
    {{"name": "Expertise", "group": "core", "score": 0, "priority": 5, "evidence": "why"}}
  ],
  "overall_fit_score": 0,
  "recommendation_status": "Rejected|Review|Shortlisted",
  "job_requirement_alignment": "clear explanation of how the resume matches or misses the selected job requirements",
  "resume_evidence_summary": "concise summary of the strongest evidence found directly inside the resume",
  "final_decision_reason": "clear final reason for the recommendation based on job requirements and resume evidence",
  "ranking_basis": "why this candidate should be ranked at this level for this job",
  "candidate_has": [
    {{"text": "has strong Python and Flask backend experience", "priority": 5}}
  ],
  "candidate_missing": [
    {{"text": "missing measurable production-scale impact", "priority": 4}}
  ],
  "pros": [
    {{"text": "strong backend expertise", "priority": 5}}
  ],
  "cons": [
    {{"text": "limited production scale detail", "priority": 3}}
  ],
  "risks": [
    {{"text": "could have shallow skills in deployment", "priority": 4}}
  ],
  "blindspots": [
    {{"text": "missing measurable impact", "priority": 4}}
  ],
  "summary": {{
    "matched_skill_count": 0,
    "required_skill_count": 0,
    "reasoning": "brief explanation",
    "profile_summary": "one paragraph on suitability"
  }}
}}
"""
    try:
        response = client.chat.completions.create(
            model=FEATHERLESS_MODEL,
            messages=[
                {"role": "system", "content": "You return only valid JSON with no markdown."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1200,
            temperature=0.2,
        )
        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.strip("`")
            content = content.replace("json", "", 1).strip()
        parsed = json.loads(content)
        parsed["skills"] = sorted(set(parsed.get("skills", [])))
        parsed["matched_skills"] = sorted(set(parsed.get("matched_skills", [])))
        parsed["keywords_found"] = sorted(set(parsed.get("keywords_found", [])))
        parsed["projects"] = parsed.get("projects", [])
        parsed["achievements"] = parsed.get("achievements", [])
        parsed["overall_fit_score"] = parsed.get("overall_fit_score", 0)
        parsed["recommendation_status"] = parsed.get("recommendation_status", "Review")
        parsed["job_requirement_alignment"] = parsed.get("job_requirement_alignment", "")
        parsed["resume_evidence_summary"] = parsed.get("resume_evidence_summary", "")
        parsed["final_decision_reason"] = parsed.get("final_decision_reason", "")
        parsed["ranking_basis"] = parsed.get("ranking_basis", "")
        parsed["candidate_has"] = parsed.get("candidate_has", [])
        parsed["candidate_missing"] = parsed.get("candidate_missing", [])
        parsed["pros"] = parsed.get("pros", [])
        parsed["cons"] = parsed.get("cons", [])
        parsed["risks"] = parsed.get("risks", [])
        parsed["blindspots"] = parsed.get("blindspots", [])
        parsed["parameter_scores"] = parsed.get("parameter_scores", [])
        parsed["cgpa"] = parsed.get("cgpa", "")
        parsed["summary"] = parsed.get("summary", {})
        return parsed
    except Exception:
        return None


def local_resume_analysis(candidate, job, resume_text):
    parsed = {
        "name": extract_candidate_name(resume_text) or candidate["name"],
        "email": extract_email(resume_text) or candidate["email"],
        "phone": extract_phone(resume_text) or candidate["phone"],
        "skills": extract_skills(resume_text),
        "experience_years": extract_experience_years(resume_text),
        "education_level": extract_education_level(resume_text),
    }
    quality = assess_resume_quality(resume_text, parsed)
    required_skills = extract_required_skills(job["requirements_text"])
    matched_skills = sorted(set(required_skills).intersection(parsed["skills"]))

    skill_score = (len(matched_skills) / len(required_skills) * 100) if required_skills else 0.0
    min_experience = float(job["min_experience"] or 0)
    experience_score = min(parsed["experience_years"] / min_experience, 1.0) * 100 if min_experience else 100.0

    required_education = education_requirement_level(job["requirements_text"])
    education_score = 100.0 if EDUCATION_RANK[parsed["education_level"]] >= EDUCATION_RANK[required_education] else 50.0
    keyword_score = compute_keyword_score(job["requirements_text"], resume_text)
    completeness_score = compute_completeness_score(parsed)
    overall_score = (
        skill_score * 0.35
        + experience_score * 0.2
        + education_score * 0.15
        + keyword_score * 0.15
        + completeness_score * 0.15
    )

    common_tokens = Counter(tokenize(resume_text))
    parameter_scores = normalize_parameter_scores(
        [
            {"name": "Expertise", "group": "core", "score": skill_score, "priority": 5, "evidence": ", ".join(matched_skills)},
            {"name": "Experience", "group": "core", "score": experience_score, "priority": 5, "evidence": f"{parsed['experience_years']} years"},
            {"name": "Education", "group": "foundation", "score": education_score, "priority": 3, "evidence": parsed["education_level"]},
            {"name": "Keyword Alignment", "group": "relevance", "score": keyword_score, "priority": 4, "evidence": ", ".join(matched_skills)},
            {"name": "Resume Quality", "group": "validation", "score": quality["quality_score"], "priority": 4, "evidence": "; ".join(quality["warnings"] or ["Adequate resume structure"])},
        ]
    )
    return {
        "extracted_name": parsed["name"],
        "extracted_email": parsed["email"],
        "extracted_phone": parsed["phone"],
        "skills": parsed["skills"],
        "matched_skills": matched_skills,
        "keywords_found": matched_skills,
        "projects": [],
        "achievements": [],
        "cgpa": "",
        "ranking_basis": "Fallback local analysis only. Featherless analysis not used.",
        "candidate_has": normalize_finding_items([{"text": f"Matched skills: {', '.join(matched_skills)}", "priority": 4}] if matched_skills else []),
        "candidate_missing": normalize_finding_items([{"text": issue, "priority": 4} for issue in quality["issues"]]),
        "pros": normalize_finding_items([{"text": f"Matched skills: {', '.join(matched_skills)}", "priority": 4}] if matched_skills else []),
        "cons": normalize_finding_items([{"text": issue, "priority": 3} for issue in quality["warnings"]]),
        "risks": normalize_finding_items([{"text": issue, "priority": 4} for issue in quality["issues"]]),
        "blindspots": normalize_finding_items([]),
        "parameter_scores": parameter_scores,
        "experience_years": round(parsed["experience_years"], 2),
        "education_level": parsed["education_level"],
        "skill_score": round(skill_score, 2),
        "experience_score": round(experience_score, 2),
        "education_score": round(education_score, 2),
        "keyword_score": round(keyword_score, 2),
        "completeness_score": round(completeness_score, 2),
        "overall_score": round(weighted_parameter_score(parameter_scores), 2),
        "quality_score": quality["quality_score"],
        "summary": {
            "matched_skill_count": len(matched_skills),
            "required_skill_count": len(required_skills),
            "reasoning": "Generated with local NLP fallback.",
            "top_resume_terms": [token for token, _count in common_tokens.most_common(12)],
            "validation_issues": quality["issues"],
            "quality_warnings": quality["warnings"],
            "profile_summary": f"Candidate shows {len(matched_skills)} matched required skills and {parsed['experience_years']} years estimated experience.",
        },
    }


def analyze_resume(candidate, job, resume_text):
    llm_result = featherless_resume_analysis(candidate, job, resume_text)
    if llm_result:
        required_skills = extract_required_skills(job["requirements_text"])
        llm_result["parameter_scores"] = normalize_parameter_scores(llm_result.get("parameter_scores", []))
        if not llm_result["parameter_scores"]:
            raise RuntimeError("Featherless returned incomplete analysis. Please retry with a clearer resume.")
        llm_result["candidate_has"] = normalize_finding_items(llm_result.get("candidate_has", []))
        llm_result["candidate_missing"] = normalize_finding_items(llm_result.get("candidate_missing", []))
        llm_result["pros"] = normalize_finding_items(llm_result.get("pros", []))
        llm_result["cons"] = normalize_finding_items(llm_result.get("cons", []))
        llm_result["risks"] = normalize_finding_items(llm_result.get("risks", []))
        llm_result["blindspots"] = normalize_finding_items(llm_result.get("blindspots", []))
        llm_result["projects"] = [str(item).strip() for item in llm_result.get("projects", []) if str(item).strip()]
        llm_result["achievements"] = [str(item).strip() for item in llm_result.get("achievements", []) if str(item).strip()]
        llm_result["cgpa"] = str(llm_result.get("cgpa", "") or "").strip()
        llm_result["job_requirement_alignment"] = str(llm_result.get("job_requirement_alignment", "") or "").strip()
        llm_result["resume_evidence_summary"] = str(llm_result.get("resume_evidence_summary", "") or "").strip()
        llm_result["final_decision_reason"] = str(llm_result.get("final_decision_reason", "") or "").strip()
        llm_result["ranking_basis"] = str(llm_result.get("ranking_basis", "") or "").strip()
        llm_result["matched_skills"] = sorted(set(llm_result.get("matched_skills", [])).intersection(required_skills or llm_result.get("matched_skills", [])))
        llm_result["skill_score"] = round(weighted_parameter_score([item for item in llm_result["parameter_scores"] if item["name"].lower() in {"expertise", "technical depth", "role relevance"} or item["group"] == "core"]), 2)
        llm_result["experience_score"] = round(weighted_parameter_score([item for item in llm_result["parameter_scores"] if "experience" in item["name"].lower()]), 2)
        llm_result["project_score"] = round(weighted_parameter_score([item for item in llm_result["parameter_scores"] if "project" in item["name"].lower()]), 2)
        llm_result["achievement_score"] = round(weighted_parameter_score([item for item in llm_result["parameter_scores"] if "achievement" in item["name"].lower() or "impact" in item["name"].lower()]), 2)
        llm_result["education_score"] = round(weighted_parameter_score([item for item in llm_result["parameter_scores"] if "education" in item["name"].lower() or "cgpa" in item["name"].lower()]), 2)
        llm_result["keyword_score"] = round(weighted_parameter_score([item for item in llm_result["parameter_scores"] if "keyword" in item["name"].lower() or item["group"] == "relevance"]), 2)
        llm_result["completeness_score"] = round(weighted_parameter_score([item for item in llm_result["parameter_scores"] if item["group"] == "validation"]), 2)
        api_overall = float(llm_result.get("overall_fit_score", 0) or 0)
        llm_result["overall_score"] = round(api_overall if api_overall > 0 else weighted_parameter_score(llm_result["parameter_scores"]), 2)
        llm_result["experience_years"] = round(float(llm_result.get("experience_years", 0)), 2)
        llm_result["quality_score"] = llm_result["completeness_score"] or round(weighted_parameter_score(llm_result["parameter_scores"]), 2)
        llm_result["summary"] = llm_result.get("summary", {})
        llm_result["summary"]["matched_skill_count"] = llm_result["summary"].get("matched_skill_count", len(llm_result["matched_skills"]))
        llm_result["summary"]["required_skill_count"] = llm_result["summary"].get("required_skill_count", len(required_skills))
        llm_result["summary"]["projects"] = llm_result["projects"]
        llm_result["summary"]["achievements"] = llm_result["achievements"]
        llm_result["summary"]["keywords_found"] = llm_result["keywords_found"]
        llm_result["summary"]["cgpa"] = llm_result["cgpa"]
        llm_result["summary"]["candidate_has"] = llm_result["candidate_has"]
        llm_result["summary"]["candidate_missing"] = llm_result["candidate_missing"]
        llm_result["summary"]["job_requirement_alignment"] = llm_result["job_requirement_alignment"]
        llm_result["summary"]["resume_evidence_summary"] = llm_result["resume_evidence_summary"]
        llm_result["summary"]["final_decision_reason"] = llm_result["final_decision_reason"]
        llm_result["summary"]["ranking_basis"] = llm_result["ranking_basis"]
        llm_result["summary"]["validation_issues"] = [item["text"] for item in llm_result["blindspots"]]
        llm_result["summary"]["quality_warnings"] = [item["text"] for item in llm_result["cons"]]
        llm_result["analysis_source"] = "featherless"
        return finalize_decision(llm_result, job)
    raise RuntimeError("Featherless analysis is unavailable. Set a valid FEATHERLESS_API_KEY and try again.")


def generate_candidate_code(candidate_id):
    return f"CAN-{candidate_id:04d}"


def enrich_job(job):
    if not job:
        return None
    item = dict(job)
    item["requirements_list"] = [part.strip() for part in str(item.get("requirements_text", "")).split(",") if part.strip()]
    item["responsibilities_list"] = [part.strip() for part in str(item.get("responsibilities_text", "")).split(",") if part.strip()]
    item["qualifications_list"] = [part.strip() for part in str(item.get("qualifications_text", "")).split(",") if part.strip()]
    item["preferred_list"] = [part.strip() for part in str(item.get("preferred_text", "")).split(",") if part.strip()]
    return item


def fetch_analysis_parameters(analysis_id):
    return db_fetchall(
        """
        SELECT id, parameter_name, parameter_group, score, priority, evidence
        FROM analysis_parameters
        WHERE analysis_id = :analysis_id
        ORDER BY priority DESC, score DESC, id ASC
        """,
        {"analysis_id": analysis_id},
    )


def fetch_analysis_findings(analysis_id):
    rows = db_fetchall(
        """
        SELECT finding_type, finding_text, priority
        FROM analysis_findings
        WHERE analysis_id = :analysis_id
        ORDER BY priority DESC, id ASC
        """,
        {"analysis_id": analysis_id},
    )
    grouped = {"pros": [], "cons": [], "risks": [], "blindspots": [], "candidate_has": [], "candidate_missing": []}
    for row in rows:
        finding_type = str(row["finding_type"]).lower()
        if finding_type in grouped:
            grouped[finding_type].append(row)
    return grouped


def hydrate_application_record(data):
    if not data:
        return None
    item = dict(data)
    item["skill_score"] = item.get("skill_score", item.get("expertise_score", 0))
    item["completeness_score"] = item.get("completeness_score", item.get("project_score", 0))
    item["skills"] = json.loads(item["skills_json"]) if item.get("skills_json") else []
    item["matched_skills"] = json.loads(item["matched_skills_json"]) if item.get("matched_skills_json") else []
    item["summary"] = json.loads(item["summary_json"]) if item.get("summary_json") else {}
    item["quality_score"] = item["summary"].get("quality_score", item.get("quality_score", 0))
    item["fit_label"] = item["summary"].get("fit_label", item.get("status", "Pending"))
    item["rejection_reasons"] = item["summary"].get("rejection_reasons", [])
    item["quality_warnings"] = item["summary"].get("quality_warnings", [])
    item["projects"] = item["summary"].get("projects", [])
    item["achievements"] = item["summary"].get("achievements", [])
    item["keywords_found"] = item["summary"].get("keywords_found", [])
    item["cgpa"] = item["summary"].get("cgpa", "")
    item["profile_summary"] = item["summary"].get("profile_summary", "")
    item["job_requirement_alignment"] = item["summary"].get("job_requirement_alignment", "")
    item["resume_evidence_summary"] = item["summary"].get("resume_evidence_summary", "")
    item["final_decision_reason"] = item["summary"].get("final_decision_reason", "")
    item["ranking_basis"] = item["summary"].get("ranking_basis", "")
    item["candidate_has"] = item["summary"].get("candidate_has", [])
    item["candidate_missing"] = item["summary"].get("candidate_missing", [])
    if item.get("id"):
        item["parameter_scores"] = fetch_analysis_parameters(item["id"])
        findings = fetch_analysis_findings(item["id"])
        item["pros"] = findings["pros"]
        item["cons"] = findings["cons"]
        item["risks"] = findings["risks"]
        item["blindspots"] = findings["blindspots"]
        if findings["candidate_has"]:
            item["candidate_has"] = findings["candidate_has"]
        if findings["candidate_missing"]:
            item["candidate_missing"] = findings["candidate_missing"]
    else:
        item["parameter_scores"] = []
        item["pros"] = []
        item["cons"] = []
        item["risks"] = []
        item["blindspots"] = []
        item["candidate_has"] = []
        item["candidate_missing"] = []
    return item


def fetch_candidate(candidate_id):
    return db_fetchone("SELECT * FROM candidates WHERE id = :candidate_id", {"candidate_id": candidate_id})


def fetch_jobs():
    return [enrich_job(job) for job in db_fetchall("SELECT * FROM jobs WHERE is_active = 1 ORDER BY created_at DESC, id DESC")]


def fetch_job(job_id):
    return enrich_job(db_fetchone("SELECT * FROM jobs WHERE id = :job_id AND is_active = 1", {"job_id": job_id}))


def fetch_latest_application(candidate_id):
    row = db_fetchone(
        """
        SELECT
            ja.id AS application_id,
            ja.cover_note,
            ja.status,
            ja.created_at AS applied_at,
            j.title,
            a.*
        FROM job_applications ja
        JOIN jobs j ON j.id = ja.job_id
        LEFT JOIN analyses a ON a.application_id = ja.id
        WHERE ja.candidate_id = :candidate_id
        ORDER BY ja.created_at DESC, ja.id DESC
        """,
        {"candidate_id": candidate_id},
    )
    return hydrate_application_record(row)


def fetch_admin_rankings(job_id=None):
    query = """
        SELECT
            c.id AS candidate_id,
            c.candidate_code,
            c.candidate_index,
            c.name,
            c.email,
            c.phone,
            j.id AS job_id,
            j.title AS job_title,
            a.expertise_score AS skill_score,
            a.experience_score,
            a.education_score,
            a.keyword_score,
            a.project_score,
            a.achievement_score,
            a.summary_json,
            a.overall_score,
            a.analysis_source,
            ja.status,
            a.created_at,
            a.id AS analysis_id,
            ja.id AS application_id
        FROM analyses a
        JOIN job_applications ja ON ja.id = a.application_id
        JOIN candidates c ON c.id = ja.candidate_id
        JOIN jobs j ON j.id = ja.job_id
        {where_clause}
        ORDER BY a.created_at DESC, a.id DESC
        """
    params = {}
    where_clause = ""
    if job_id:
        where_clause = "WHERE j.id = :job_id"
        params["job_id"] = job_id
    rows = db_fetchall(query.format(where_clause=where_clause), params)

    seen = set()
    rankings = []
    for row in rows:
        if row["candidate_id"] in seen:
            continue
        seen.add(row["candidate_id"])
        item = dict(row)
        item["summary"] = json.loads(item["summary_json"]) if item.get("summary_json") else {}
        item["fit_label"] = item["summary"].get("fit_label", item.get("status", "Pending"))
        item["rejection_reasons"] = item["summary"].get("rejection_reasons", [])
        item["quality_warnings"] = item["summary"].get("quality_warnings", [])
        item["completeness_score"] = item["summary"].get("quality_score", item.get("project_score", 0))
        rankings.append(item)
    rankings.sort(key=lambda item: item["overall_score"], reverse=True)
    return rankings


def fetch_admin_candidate_detail(job_id, candidate_id):
    row = db_fetchone(
        """
        SELECT
            ja.id AS application_id,
            ja.cover_note,
            ja.status,
            ja.created_at AS applied_at,
            c.id AS candidate_id,
            c.candidate_code,
            c.candidate_index,
            c.name,
            c.email,
            c.phone,
            j.id AS job_id,
            j.title,
            j.summary AS job_summary,
            j.requirements_text,
            j.min_experience,
            a.*
        FROM job_applications ja
        JOIN candidates c ON c.id = ja.candidate_id
        JOIN jobs j ON j.id = ja.job_id
        JOIN analyses a ON a.application_id = ja.id
        WHERE ja.job_id = :job_id AND ja.candidate_id = :candidate_id
        ORDER BY a.created_at DESC, a.id DESC
        FETCH FIRST 1 ROWS ONLY
        """,
        {"job_id": job_id, "candidate_id": candidate_id},
    )
    detail = hydrate_application_record(row)
    if detail:
        detail["requirements_list"] = [part.strip() for part in str(detail.get("requirements_text", "")).split(",") if part.strip()]
    return detail


def create_admin_charts(rankings):
    if not rankings:
        return

    names = [row["name"] for row in rankings]
    overall = [row["overall_score"] for row in rankings]
    skill = [row["skill_score"] for row in rankings]
    experience = [row["experience_score"] for row in rankings]
    education = [row["education_score"] for row in rankings]
    keyword = [row["keyword_score"] for row in rankings]
    completeness = [row["completeness_score"] for row in rankings]

    plt.figure(figsize=(10, 5))
    bars = plt.bar(names, overall, color="#115e59")
    plt.title("Overall Candidate Ranking")
    plt.ylim(0, 100)
    plt.ylabel("Score (%)")
    plt.xticks(rotation=18, ha="right")
    for bar, score in zip(bars, overall):
        plt.text(bar.get_x() + bar.get_width() / 2, score + 1, f"{score:.1f}", ha="center", fontsize=8)
    plt.tight_layout()
    plt.savefig(STATIC_DIR / "overall_ranking.png", dpi=160)
    plt.close()

    width = 0.15
    x_axis = list(range(len(rankings)))
    plt.figure(figsize=(12, 6))
    plt.bar([x - 2 * width for x in x_axis], skill, width=width, label="Skill")
    plt.bar([x - width for x in x_axis], experience, width=width, label="Experience")
    plt.bar(x_axis, education, width=width, label="Education")
    plt.bar([x + width for x in x_axis], keyword, width=width, label="Keyword")
    plt.bar([x + 2 * width for x in x_axis], completeness, width=width, label="Completeness")
    plt.xticks(x_axis, names, rotation=18, ha="right")
    plt.ylim(0, 100)
    plt.ylabel("Score (%)")
    plt.title("Candidate Comparison by Parameter")
    plt.legend()
    plt.tight_layout()
    plt.savefig(STATIC_DIR / "parameter_comparison.png", dpi=160)
    plt.close()


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form["phone"].strip()
        password = request.form["password"]

        existing = db_fetchone("SELECT id FROM candidates WHERE email = :email", {"email": email})
        if existing:
            flash("A candidate with this email already exists.", "error")
            return redirect(url_for("register"))

        candidate_id = next_id("candidates")
        candidate_code = generate_candidate_code(candidate_id)
        db_execute(
            """
            INSERT INTO candidates (id, candidate_code, candidate_index, name, email, phone, password_hash, created_at)
            VALUES (:id, :candidate_code, :candidate_index, :name, :email, :phone, :password_hash, :created_at)
            """,
            {
                "id": candidate_id,
                "candidate_code": candidate_code,
                "candidate_index": candidate_id,
                "name": name,
                "email": email,
                "phone": phone,
                "password_hash": generate_password_hash(password),
                "created_at": datetime.utcnow().isoformat(),
            },
        )
        db_commit()

        flash(f"Registration complete. Your candidate ID is {candidate_code}.", "success")
        return redirect(url_for("candidate_login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def candidate_login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        row = db_fetchone("SELECT * FROM candidates WHERE email = :email", {"email": email})
        if not row or not check_password_hash(row["password_hash"], password):
            flash("Invalid candidate credentials.", "error")
            return redirect(url_for("candidate_login"))
        session.clear()
        session["role"] = "candidate"
        session["user_id"] = row["id"]
        return redirect(url_for("candidate_jobs"))
    return render_template("candidate_login.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        row = db_fetchone("SELECT * FROM admins WHERE username = :username", {"username": username})
        if not row or not check_password_hash(row["password_hash"], password):
            flash("Invalid admin credentials.", "error")
            return redirect(url_for("admin_login"))
        session.clear()
        session["role"] = "admin"
        session["user_id"] = row["id"]
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


@app.route("/candidate/jobs")
@login_required("candidate")
def candidate_jobs():
    return render_template(
        "candidate_jobs.html",
        candidate=fetch_candidate(session["user_id"]),
        jobs=fetch_jobs(),
        latest_application=fetch_latest_application(session["user_id"]),
    )


@app.route("/candidate/jobs/<int:job_id>/apply", methods=["GET", "POST"])
@login_required("candidate")
def apply_job(job_id):
    candidate = fetch_candidate(session["user_id"])
    job = fetch_job(job_id)
    if not job:
        flash("Job requirement not found.", "error")
        return redirect(url_for("candidate_jobs"))

    if request.method == "POST":
        upload = request.files.get("resume")
        cover_note = request.form.get("cover_note", "").strip()
        if not upload or upload.filename == "":
            flash("Please select a Word resume file.", "error")
            return redirect(url_for("apply_job", job_id=job_id))
        if not allowed_file(upload.filename):
            flash("Only .docx resume uploads are supported.", "error")
            return redirect(url_for("apply_job", job_id=job_id))

        filename = secure_filename(upload.filename)
        stored_name = f"{candidate['candidate_code']}_{job_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
        stored_path = UPLOAD_DIR / stored_name
        upload.save(stored_path)

        try:
            resume_text = extract_resume_text(stored_path)
        except Exception:
            stored_path.unlink(missing_ok=True)
            flash("The uploaded document could not be read.", "error")
            return redirect(url_for("apply_job", job_id=job_id))

        try:
            analysis = analyze_resume(candidate, job, resume_text)
        except RuntimeError as exc:
            stored_path.unlink(missing_ok=True)
            flash(str(exc), "error")
            return redirect(url_for("apply_job", job_id=job_id))
        resume_id = next_id("resumes")
        db_execute(
            """
            INSERT INTO resumes (id, candidate_id, original_filename, stored_path, raw_text, uploaded_at)
            VALUES (:id, :candidate_id, :original_filename, :stored_path, :raw_text, :uploaded_at)
            """,
            {
                "id": resume_id,
                "candidate_id": candidate["id"],
                "original_filename": filename,
                "stored_path": str(stored_path),
                "raw_text": resume_text,
                "uploaded_at": datetime.utcnow().isoformat(),
            },
        )
        application_id = next_id("job_applications")
        db_execute(
            """
            INSERT INTO job_applications (id, candidate_id, job_id, resume_id, cover_note, status, created_at)
            VALUES (:id, :candidate_id, :job_id, :resume_id, :cover_note, :status, :created_at)
            """,
            {
                "id": application_id,
                "candidate_id": candidate["id"],
                "job_id": job["id"],
                "resume_id": resume_id,
                "cover_note": cover_note,
                "status": analysis["status"],
                "created_at": datetime.utcnow().isoformat(),
            },
        )
        analysis_id = next_id("analyses")
        db_execute(
            """
            INSERT INTO analyses (
                id, application_id, expertise_score, experience_score, project_score, achievement_score,
                education_score, keyword_score, overall_score, extracted_name, extracted_email, extracted_phone,
                skills_json, matched_skills_json, projects_json, achievements_json, keywords_json,
                experience_years, education_level, cgpa, ranking_basis, profile_summary, summary_json,
                analysis_source, created_at
            ) VALUES (
                :id, :application_id, :expertise_score, :experience_score, :project_score, :achievement_score,
                :education_score, :keyword_score, :overall_score, :extracted_name, :extracted_email, :extracted_phone,
                :skills_json, :matched_skills_json, :projects_json, :achievements_json, :keywords_json,
                :experience_years, :education_level, :cgpa, :ranking_basis, :profile_summary, :summary_json,
                :analysis_source, :created_at
            )
            """,
            {
                "id": analysis_id,
                "application_id": application_id,
                "expertise_score": analysis["skill_score"],
                "experience_score": analysis["experience_score"],
                "project_score": analysis.get("project_score", 0),
                "achievement_score": analysis.get("achievement_score", 0),
                "education_score": analysis["education_score"],
                "keyword_score": analysis["keyword_score"],
                "overall_score": analysis["overall_score"],
                "extracted_name": analysis["extracted_name"],
                "extracted_email": analysis["extracted_email"],
                "extracted_phone": analysis["extracted_phone"],
                "skills_json": json.dumps(analysis["skills"]),
                "matched_skills_json": json.dumps(analysis["matched_skills"]),
                "projects_json": json.dumps(analysis.get("projects", [])),
                "achievements_json": json.dumps(analysis.get("achievements", [])),
                "keywords_json": json.dumps(analysis.get("keywords_found", [])),
                "experience_years": analysis["experience_years"],
                "education_level": analysis["education_level"],
                "cgpa": analysis.get("cgpa", ""),
                "ranking_basis": analysis.get("ranking_basis", ""),
                "profile_summary": analysis["summary"].get("profile_summary", ""),
                "summary_json": json.dumps(
                    {
                        **analysis["summary"],
                        "quality_score": analysis["quality_score"],
                        "projects": analysis.get("projects", []),
                        "achievements": analysis.get("achievements", []),
                        "keywords_found": analysis.get("keywords_found", []),
                        "cgpa": analysis.get("cgpa", ""),
                    }
                ),
                "analysis_source": analysis["analysis_source"],
                "created_at": datetime.utcnow().isoformat(),
            },
        )
        for parameter in analysis.get("parameter_scores", []):
            db_execute(
                """
                INSERT INTO analysis_parameters (
                    id, analysis_id, parameter_name, parameter_group, score, priority, evidence
                ) VALUES (
                    :id, :analysis_id, :parameter_name, :parameter_group, :score, :priority, :evidence
                )
                """,
                {
                    "id": next_id("analysis_parameters"),
                    "analysis_id": analysis_id,
                    "parameter_name": parameter["name"],
                    "parameter_group": parameter["group"],
                    "score": parameter["score"],
                    "priority": parameter["priority"],
                    "evidence": parameter["evidence"],
                },
            )
        for finding_type in ("candidate_has", "candidate_missing", "pros", "cons", "risks", "blindspots"):
            for finding in analysis.get(finding_type, []):
                db_execute(
                    """
                    INSERT INTO analysis_findings (
                        id, analysis_id, finding_type, finding_text, priority
                    ) VALUES (
                        :id, :analysis_id, :finding_type, :finding_text, :priority
                    )
                    """,
                    {
                        "id": next_id("analysis_findings"),
                        "analysis_id": analysis_id,
                        "finding_type": finding_type,
                        "finding_text": finding["text"],
                        "priority": finding["priority"],
                    },
                )
        db_commit()

        if analysis["status"] == "Rejected":
            had_text = ", ".join(item["text"] for item in analysis.get("candidate_has", [])[:3])
            missing_text = ", ".join(item["text"] for item in analysis.get("candidate_missing", [])[:3])
            rejection_text = " ".join(analysis.get("rejection_reasons", [])) or "The resume did not meet the job requirements."
            if had_text:
                rejection_text += f" Strengths identified: {had_text}."
            if missing_text:
                rejection_text += f" Missing or weak areas: {missing_text}."
            flash(f"Application rejected. {rejection_text}", "error")
        elif analysis["status"] == "Review":
            flash("Resume analysed. Your application needs manual review before shortlisting.", "success")
        else:
            flash("Resume analysed successfully. Your profile has been shortlisted for this role.", "success")
        return redirect(url_for("candidate_jobs"))

    return render_template("apply_job.html", candidate=candidate, job=job)


@app.route("/admin/jobs", methods=["POST"])
@login_required("admin")
def create_job():
    title = request.form["title"].strip()
    department = request.form["department"].strip()
    location = request.form["location"].strip()
    employment_type = request.form["employment_type"].strip()
    summary = request.form["summary"].strip()
    role_overview = request.form["role_overview"].strip()
    responsibilities_text = request.form["responsibilities_text"].strip()
    qualifications_text = request.form["qualifications_text"].strip()
    preferred_text = request.form.get("preferred_text", "").strip()
    requirements_text = request.form["requirements_text"].strip()
    min_experience = float(request.form["min_experience"])
    db_execute(
        """
        INSERT INTO jobs (
            id, title, department, location, employment_type, summary, role_overview,
            responsibilities_text, qualifications_text, preferred_text, requirements_text,
            min_experience, is_active, created_at
        ) VALUES (
            :id, :title, :department, :location, :employment_type, :summary, :role_overview,
            :responsibilities_text, :qualifications_text, :preferred_text, :requirements_text,
            :min_experience, 1, :created_at
        )
        """,
        {
            "id": next_id("jobs"),
            "title": title,
            "department": department,
            "location": location,
            "employment_type": employment_type,
            "summary": summary,
            "role_overview": role_overview,
            "responsibilities_text": responsibilities_text,
            "qualifications_text": qualifications_text,
            "preferred_text": preferred_text,
            "requirements_text": requirements_text,
            "min_experience": min_experience,
            "created_at": datetime.utcnow().isoformat(),
        },
    )
    db_commit()
    flash("New job requirement added.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/dashboard")
@login_required("admin")
def admin_dashboard():
    jobs = fetch_jobs()
    selected_job_id = request.args.get("job_id", type=int)
    selected_candidate_id = request.args.get("candidate_id", type=int)
    if not selected_job_id and jobs:
        selected_job_id = jobs[0]["id"]
    selected_job = fetch_job(selected_job_id) if selected_job_id else None
    rankings = fetch_admin_rankings(selected_job_id)
    create_admin_charts(rankings)
    selected_candidate = None
    if selected_job_id and selected_candidate_id:
        selected_candidate = fetch_admin_candidate_detail(selected_job_id, selected_candidate_id)
    elif selected_job_id and rankings:
        selected_candidate = fetch_admin_candidate_detail(selected_job_id, rankings[0]["candidate_id"])
    average_score = round(sum(row["overall_score"] for row in rankings) / len(rankings), 2) if rankings else 0.0
    top_score = round(max((row["overall_score"] for row in rankings), default=0.0), 2)
    return render_template(
        "admin_dashboard.html",
        rankings=rankings,
        jobs=jobs,
        selected_job=selected_job,
        selected_job_id=selected_job_id,
        selected_candidate=selected_candidate,
        stats={
            "total_candidates": len(rankings),
            "average_score": average_score,
            "top_score": top_score,
            "total_jobs": len(jobs),
        },
        chart_stamp=datetime.utcnow().strftime("%Y%m%d%H%M%S"),
    )


if __name__ == "__main__":
    with app.app_context():
        initialize_database()
    app.run(debug=True)
