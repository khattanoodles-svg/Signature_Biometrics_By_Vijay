BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE analysis_findings CASCADE CONSTRAINTS';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN
            RAISE;
        END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE analysis_parameters CASCADE CONSTRAINTS';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN
            RAISE;
        END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE analyses CASCADE CONSTRAINTS';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN
            RAISE;
        END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE job_applications CASCADE CONSTRAINTS';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN
            RAISE;
        END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE resumes CASCADE CONSTRAINTS';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN
            RAISE;
        END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE jobs CASCADE CONSTRAINTS';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN
            RAISE;
        END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE admins CASCADE CONSTRAINTS';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN
            RAISE;
        END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE candidates CASCADE CONSTRAINTS';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN
            RAISE;
        END IF;
END;
/

CREATE TABLE candidates (
    id NUMBER PRIMARY KEY,
    candidate_code VARCHAR2(40) UNIQUE NOT NULL,
    candidate_index NUMBER UNIQUE NOT NULL,
    name VARCHAR2(200) NOT NULL,
    email VARCHAR2(200) UNIQUE NOT NULL,
    phone VARCHAR2(50) NOT NULL,
    password_hash VARCHAR2(255) NOT NULL,
    created_at VARCHAR2(40) NOT NULL
);

CREATE TABLE admins (
    id NUMBER PRIMARY KEY,
    username VARCHAR2(100) UNIQUE NOT NULL,
    password_hash VARCHAR2(255) NOT NULL,
    created_at VARCHAR2(40) NOT NULL
);

CREATE TABLE jobs (
    id NUMBER PRIMARY KEY,
    title VARCHAR2(200) NOT NULL,
    department VARCHAR2(150) NOT NULL,
    location VARCHAR2(150) NOT NULL,
    employment_type VARCHAR2(80) NOT NULL,
    summary VARCHAR2(1000) NOT NULL,
    role_overview CLOB NOT NULL,
    responsibilities_text CLOB NOT NULL,
    qualifications_text CLOB NOT NULL,
    preferred_text CLOB,
    requirements_text CLOB NOT NULL,
    min_experience NUMBER(6,2) DEFAULT 0 NOT NULL,
    is_active NUMBER(1) DEFAULT 1 NOT NULL,
    created_at VARCHAR2(40) NOT NULL
);

CREATE TABLE resumes (
    id NUMBER PRIMARY KEY,
    candidate_id NUMBER NOT NULL,
    original_filename VARCHAR2(255) NOT NULL,
    stored_path VARCHAR2(500) NOT NULL,
    raw_text CLOB NOT NULL,
    uploaded_at VARCHAR2(40) NOT NULL,
    CONSTRAINT fk_resumes_candidate FOREIGN KEY (candidate_id) REFERENCES candidates(id)
);

CREATE TABLE job_applications (
    id NUMBER PRIMARY KEY,
    candidate_id NUMBER NOT NULL,
    job_id NUMBER NOT NULL,
    resume_id NUMBER NOT NULL,
    cover_note CLOB,
    status VARCHAR2(50) NOT NULL,
    created_at VARCHAR2(40) NOT NULL,
    CONSTRAINT fk_job_app_candidate FOREIGN KEY (candidate_id) REFERENCES candidates(id),
    CONSTRAINT fk_job_app_job FOREIGN KEY (job_id) REFERENCES jobs(id),
    CONSTRAINT fk_job_app_resume FOREIGN KEY (resume_id) REFERENCES resumes(id)
);

CREATE TABLE analyses (
    id NUMBER PRIMARY KEY,
    application_id NUMBER NOT NULL,
    expertise_score NUMBER(6,2) NOT NULL,
    experience_score NUMBER(6,2) NOT NULL,
    project_score NUMBER(6,2) NOT NULL,
    achievement_score NUMBER(6,2) NOT NULL,
    education_score NUMBER(6,2) NOT NULL,
    keyword_score NUMBER(6,2) NOT NULL,
    overall_score NUMBER(6,2) NOT NULL,
    extracted_name VARCHAR2(200),
    extracted_email VARCHAR2(200),
    extracted_phone VARCHAR2(50),
    skills_json CLOB NOT NULL,
    matched_skills_json CLOB NOT NULL,
    projects_json CLOB NOT NULL,
    achievements_json CLOB NOT NULL,
    keywords_json CLOB NOT NULL,
    experience_years NUMBER(6,2) NOT NULL,
    education_level VARCHAR2(50) NOT NULL,
    cgpa VARCHAR2(50),
    ranking_basis CLOB NOT NULL,
    profile_summary CLOB NOT NULL,
    summary_json CLOB NOT NULL,
    analysis_source VARCHAR2(50) NOT NULL,
    created_at VARCHAR2(40) NOT NULL,
    CONSTRAINT fk_analyses_application FOREIGN KEY (application_id) REFERENCES job_applications(id)
);

CREATE TABLE analysis_parameters (
    id NUMBER PRIMARY KEY,
    analysis_id NUMBER NOT NULL,
    parameter_name VARCHAR2(100) NOT NULL,
    parameter_group VARCHAR2(100) NOT NULL,
    score NUMBER(6,2) NOT NULL,
    priority NUMBER(3) NOT NULL,
    evidence CLOB,
    CONSTRAINT fk_analysis_parameters FOREIGN KEY (analysis_id) REFERENCES analyses(id)
);

CREATE TABLE analysis_findings (
    id NUMBER PRIMARY KEY,
    analysis_id NUMBER NOT NULL,
    finding_type VARCHAR2(50) NOT NULL,
    finding_text CLOB NOT NULL,
    priority NUMBER(3) NOT NULL,
    CONSTRAINT fk_analysis_findings FOREIGN KEY (analysis_id) REFERENCES analyses(id)
);
