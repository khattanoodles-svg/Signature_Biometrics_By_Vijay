from datetime import datetime
from pathlib import Path

from flask import g
from werkzeug.security import generate_password_hash

try:
    import oracledb
except ImportError:  # pragma: no cover
    oracledb = None


ORACLE_USER = "system"
ORACLE_PASSWORD = "mgit"
ORACLE_DSN = "localhost:1521/XE"


def normalize_value(value):
    if value is None:
        return None
    if hasattr(value, "read") and value.__class__.__name__ == "LOB":
        return value.read()
    return value


def row_to_dict(cursor, row):
    return {column[0].lower(): normalize_value(value) for column, value in zip(cursor.description, row)}


def get_db():
    if "db" not in g:
        if oracledb is None:
            raise RuntimeError("The 'oracledb' package is required for Oracle connections.")
        g.db = oracledb.connect(user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=ORACLE_DSN)
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def execute_with_connection(connection, query, params=None):
    params = params or {}
    cursor = connection.cursor()
    cursor.execute(query, params)
    return cursor


def fetchone_with_connection(connection, query, params=None):
    params = params or {}
    cursor = connection.cursor()
    cursor.execute(query, params)
    row = cursor.fetchone()
    return row_to_dict(cursor, row) if row else None


def fetchall_with_connection(connection, query, params=None):
    params = params or {}
    cursor = connection.cursor()
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [row_to_dict(cursor, row) for row in rows]


def db_execute(query, params=None):
    return execute_with_connection(get_db(), query, params)


def db_fetchone(query, params=None):
    return fetchone_with_connection(get_db(), query, params)


def db_fetchall(query, params=None):
    return fetchall_with_connection(get_db(), query, params)


def db_commit():
    get_db().commit()


def next_id_for_table(connection, table_name):
    row = fetchone_with_connection(connection, f"SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM {table_name}")
    return int(row["next_id"]) if row else 1


def next_id(table_name):
    return next_id_for_table(get_db(), table_name)


def seed_admin(connection):
    row = fetchone_with_connection(connection, "SELECT id FROM admins WHERE username = :username", {"username": "admin"})
    if row:
        return
    admin_id = next_id_for_table(connection, "admins")
    execute_with_connection(
        connection,
        "INSERT INTO admins (id, username, password_hash, created_at) VALUES (:id, :username, :password_hash, :created_at)",
        {
            "id": admin_id,
            "username": "admin",
            "password_hash": generate_password_hash("admin123"),
            "created_at": datetime.utcnow().isoformat(),
        },
    )


def seed_jobs(connection):
    row = fetchone_with_connection(connection, "SELECT COUNT(*) AS total FROM jobs")
    if row and row["total"]:
        return

    jobs = [
        (
            "Data Analyst",
            "Business Intelligence",
            "Bengaluru",
            "Full Time",
            "Analyse business performance data and turn it into reports, dashboards, and operational recommendations.",
            "Work with structured and semi-structured data to support decision making across product, sales, and operations teams.",
            "Collect and clean datasets, build KPI dashboards, perform trend analysis, explain findings to stakeholders, and support recurring reporting cycles.",
            "Bachelor degree in a quantitative discipline, strong SQL, Excel, dashboarding, statistics, communication, and analytical reasoning.",
            "Power BI, Tableau, Python, forecasting, experimentation, stakeholder management.",
            "SQL, Excel, Power BI, Tableau, data analysis, dashboarding, statistics, communication, problem solving",
            1.5,
        ),
        (
            "Backend Developer",
            "Engineering",
            "Hyderabad",
            "Full Time",
            "Build scalable APIs and backend services for customer-facing and internal products.",
            "Own backend modules, data access patterns, integrations, and service reliability for production applications.",
            "Design APIs, implement business logic, work with Oracle and relational databases, optimize queries, write maintainable code, and support deployments.",
            "Bachelor degree in computer science or equivalent, strong Python, Flask, REST API design, SQL, debugging, and systems thinking.",
            "Docker, Linux, Git workflows, caching, performance tuning, cloud deployment exposure.",
            "Python, Flask, REST API, SQL, Oracle, Git, Docker, Linux, debugging, backend architecture",
            2.0,
        ),
        (
            "NLP Engineer",
            "AI Products",
            "Remote",
            "Full Time",
            "Develop text understanding systems for resume analysis, classification, and intelligent workflow support.",
            "Work on information extraction, ranking, prompt design, and model-assisted evaluation for hiring-related text pipelines.",
            "Design prompts, evaluate model outputs, build text pipelines, integrate LLM APIs, define scoring logic, and improve extraction quality from documents.",
            "Strong Python, NLP fundamentals, prompt engineering, API integration, evaluation thinking, and SQL-based data handling.",
            "Experience with LLM evaluation, information extraction, ranking systems, and production analytics dashboards.",
            "Python, NLP, LLM, prompt engineering, text processing, information extraction, SQL, Flask, API integration, evaluation",
            2.5,
        ),
    ]
    for title, department, location, employment_type, summary, role_overview, responsibilities, qualifications, preferred, requirements, min_exp in jobs:
        job_id = next_id_for_table(connection, "jobs")
        execute_with_connection(
            connection,
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
                "id": job_id,
                "title": title,
                "department": department,
                "location": location,
                "employment_type": employment_type,
                "summary": summary,
                "role_overview": role_overview,
                "responsibilities_text": responsibilities,
                "qualifications_text": qualifications,
                "preferred_text": preferred,
                "requirements_text": requirements,
                "min_experience": min_exp,
                "created_at": datetime.utcnow().isoformat(),
            },
        )


def initialize_database():
    connection = get_db()
    seed_admin(connection)
    seed_jobs(connection)
    db_commit()
