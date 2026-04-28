"""
database.py - PostgreSQL database for courses and submissions
Stores course configurations and participant form submissions.
Reads DATABASE_URL from environment.
"""

import os
import json
import logging
from datetime import datetime

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json
from werkzeug.security import generate_password_hash

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://admin:testpass@localhost:5432/lbsnaa",
)


def get_conn():
    """Get a database connection with dict-style row access."""
    conn = psycopg2.connect(
        DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS citext")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS courses (
                    id            SERIAL PRIMARY KEY,
                    name          TEXT NOT NULL,
                    slug          TEXT NOT NULL UNIQUE,
                    description   TEXT DEFAULT '',
                    fields_config JSONB NOT NULL,
                    doc_config    JSONB NOT NULL,
                    is_active     INTEGER DEFAULT 1,
                    created_at    TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS submissions (
                    id            SERIAL PRIMARY KEY,
                    course_id     INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                    submitted_at  TEXT NOT NULL,
                    email         TEXT NOT NULL,
                    form_data     JSONB NOT NULL,
                    photo_valid   INTEGER,
                    photo_result  JSONB,
                    id_valid      INTEGER,
                    id_result     JSONB,
                    letter_valid  INTEGER,
                    letter_result JSONB,
                    photo_file    TEXT,
                    id_file       TEXT,
                    letter_file   TEXT
                )
            """)

            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_course_email
                    ON submissions(course_id, email)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_submissions_course
                    ON submissions(course_id)
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            SERIAL PRIMARY KEY,
                    username      CITEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role          TEXT NOT NULL DEFAULT 'viewer' CHECK(role IN ('admin', 'viewer')),
                    created_at    TEXT NOT NULL,
                    created_by    INTEGER REFERENCES users(id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id              SERIAL PRIMARY KEY,
                    submission_id   INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                    doc_type        TEXT NOT NULL,
                    reason          TEXT NOT NULL,
                    admin_message   TEXT DEFAULT '',
                    deadline        TEXT NOT NULL,
                    token           TEXT NOT NULL UNIQUE,
                    token_used      INTEGER DEFAULT 0,
                    email_sent_at   TEXT,
                    email_status    TEXT DEFAULT 'pending',
                    created_by      INTEGER NOT NULL REFERENCES users(id),
                    created_at      TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_notifications_submission
                    ON notifications(submission_id)
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_token
                    ON notifications(token)
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS reupload_log (
                    id              SERIAL PRIMARY KEY,
                    notification_id INTEGER NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
                    submission_id   INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                    doc_type        TEXT NOT NULL,
                    new_valid       INTEGER,
                    new_result      JSONB,
                    new_file        TEXT,
                    uploaded_at     TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_reupload_log_notification
                    ON reupload_log(notification_id)
            """)

            # Seed default admin user if no users exist
            cur.execute("SELECT COUNT(*) AS cnt FROM users")
            user_count = cur.fetchone()["cnt"]
            if user_count == 0:
                default_pw = os.environ.get('ADMIN_PASSWORD', 'admin')
                cur.execute(
                    "INSERT INTO users (username, password_hash, role, created_at) VALUES (%s, %s, %s, %s)",
                    ('admin', generate_password_hash(default_pw), 'admin', datetime.utcnow().isoformat())
                )
                logger.info("Created default admin user (username: admin)")

        conn.commit()
        logger.info("Database initialized: courses + submissions + users tables ready")
    finally:
        conn.close()


# ============================================================================
# DEFAULT CONFIGS
# ============================================================================

SERVICES_LIST = [
    "Indian Administrative Service (IAS)",
    "Indian Police Service (IPS)",
    "Indian Forest Service (IFoS)",
    "Indian Foreign Service (IFS)",
    "Indian Audit and Accounts Service (IA&AS)",
    "Indian Civil Accounts Service (ICAS)",
    "Indian Corporate Law Service (ICLS)",
    "Indian Defence Accounts Service (IDAS)",
    "Indian Defence Estates Service (IDES)",
    "Indian Information Service (IIS)",
    "Indian Ordnance Factories Service (IOFS)",
    "Indian Communication Finance Services (ICFS)",
    "Indian Postal Service (IPoS)",
    "Indian Railway Accounts Service (IRAS)",
    "Indian Railway Personnel Service (IRPS)",
    "Indian Railway Traffic Service (IRTS)",
    "Indian Revenue Service (IRS-IT)",
    "Indian Revenue Service (IRS-C&CE)",
    "Others",
]

STATES_AND_UT = {
    "States": [
        "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
        "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand",
        "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
        "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
        "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
        "Uttar Pradesh", "Uttarakhand", "West Bengal",
    ],
    "Union Territories": [
        "Andaman and Nicobar Islands", "Chandigarh",
        "Dadra and Nagar Haveli and Daman and Diu", "Delhi (NCT)",
        "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
    ],
}

CADRE_LIST = [
    "AGMUT", "Andhra Pradesh", "Assam-Meghalaya", "Bihar", "Chhattisgarh",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Nagaland",
    "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
]

ZONE_LIST = {
    "Zone-I": "AGMUT, J&K, HP, Uttarakhand, Punjab, Rajasthan, Haryana",
    "Zone-II": "UP, Bihar, Jharkhand, Odisha",
    "Zone-III": "Gujarat, Maharashtra, MP, Chhattisgarh",
    "Zone-IV": "WB, Sikkim, Assam-Meghalaya, Manipur, Tripura, Nagaland",
    "Zone-V": "Telangana, AP, Karnataka, Kerala, TN, Goa",
}

STATES_FLAT = STATES_AND_UT["States"] + STATES_AND_UT["Union Territories"]

DEFAULT_FIELDS_CONFIG = {
    "default_fields": [
        {"key": "name", "label": "Full Name", "type": "text", "enabled": True, "required": True, "locked": True},
        {"key": "email", "label": "Email", "type": "email", "enabled": True, "required": True, "locked": True},
        {"key": "i_nomination", "label": "iNomination Number", "type": "text", "enabled": True, "required": True},
        {"key": "gender", "label": "Gender", "type": "select", "enabled": True, "required": True, "options": ["Male", "Female", "Other"]},
        {"key": "job_title", "label": "Job Title", "type": "text", "enabled": True, "required": False},
        {"key": "service", "label": "Service", "type": "select", "enabled": True, "required": True, "options": SERVICES_LIST},
        {"key": "batch", "label": "Batch", "type": "text", "enabled": True, "required": True},
        {"key": "cadre", "label": "Cadre", "type": "select", "enabled": True, "required": True, "options": CADRE_LIST},
        {"key": "zone", "label": "Zone", "type": "select", "enabled": True, "required": False, "options": list(ZONE_LIST.keys())},
        {"key": "state", "label": "State", "type": "grouped_select", "enabled": True, "required": False, "option_groups": STATES_AND_UT},
        {"key": "department", "label": "Department", "type": "text", "enabled": True, "required": False},
        {"key": "mobile", "label": "Mobile", "type": "tel", "enabled": True, "required": True},
    ],
    "custom_fields": []
}

DEFAULT_DOC_CONFIG = {
    "PHOTO": {"enabled": True, "required": True, "label": "Passport Photo"},
    "ID": {"enabled": True, "required": True, "label": "Government ID"},
    "LETTER": {"enabled": True, "required": True, "label": "Nomination Letter"},
}


def get_default_fields_config():
    """Return a deep copy of the default fields config."""
    return json.loads(json.dumps(DEFAULT_FIELDS_CONFIG))


def get_default_doc_config():
    """Return a deep copy of the default doc config."""
    return json.loads(json.dumps(DEFAULT_DOC_CONFIG))


# ============================================================================
# COURSE CRUD
# ============================================================================

def create_course(name, slug, description, fields_config, doc_config):
    """Create a new course. Returns the course id."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO courses (name, slug, description, fields_config, doc_config, is_active, created_at)
                   VALUES (%s, %s, %s, %s, %s, 1, %s)
                   RETURNING id""",
                (name, slug, description, Json(fields_config), Json(doc_config), datetime.utcnow().isoformat())
            )
            course_id = cur.fetchone()["id"]
        conn.commit()
        logger.info(f"Created course '{name}' (id={course_id}, slug={slug})")
        return course_id
    finally:
        conn.close()


def get_all_courses():
    """Return all courses with submission counts."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.*, COUNT(s.id) AS submission_count
                FROM courses c
                LEFT JOIN submissions s ON s.course_id = c.id
                GROUP BY c.id
                ORDER BY c.created_at DESC
            """)
            rows = cur.fetchall()
        return [_parse_course_row(row) for row in rows]
    finally:
        conn.close()


def get_course_by_id(course_id):
    """Return a single course by id."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM courses WHERE id = %s", (course_id,))
            row = cur.fetchone()
        return _parse_course_row(row) if row else None
    finally:
        conn.close()


def get_course_by_slug(slug):
    """Return a single course by slug."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM courses WHERE slug = %s", (slug,))
            row = cur.fetchone()
        return _parse_course_row(row) if row else None
    finally:
        conn.close()


def update_course(course_id, name, slug, description, fields_config, doc_config):
    """Update an existing course."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE courses SET name=%s, slug=%s, description=%s, fields_config=%s, doc_config=%s
                   WHERE id=%s""",
                (name, slug, description, Json(fields_config), Json(doc_config), course_id)
            )
        conn.commit()
        logger.info(f"Updated course id={course_id}")
    finally:
        conn.close()


def toggle_course(course_id):
    """Toggle is_active between 0 and 1. Returns new state."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE courses SET is_active = 1 - is_active WHERE id = %s RETURNING is_active",
                (course_id,)
            )
            row = cur.fetchone()
        conn.commit()
        new_state = row["is_active"] if row else None
        logger.info(f"Toggled course id={course_id} -> is_active={new_state}")
        return new_state
    finally:
        conn.close()


def delete_course(course_id):
    """Delete a course and all its submissions (CASCADE)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM courses WHERE id = %s", (course_id,))
        conn.commit()
        logger.info(f"Deleted course id={course_id} and its submissions")
    finally:
        conn.close()


def _parse_course_row(row):
    """Convert a course db row to a dict. JSONB columns are already decoded by psycopg2."""
    if row is None:
        return None
    d = dict(row)
    if d.get("fields_config") is None:
        d["fields_config"] = get_default_fields_config()
    if d.get("doc_config") is None:
        d["doc_config"] = get_default_doc_config()
    return d


# ============================================================================
# SUBMISSION CRUD
# ============================================================================

def save_submission(course_id, email, form_data, doc_results):
    """
    Save a submission. Returns submission id.

    doc_results: dict with keys PHOTO, ID, LETTER each containing
                 {"valid": bool, "result": dict} or None
    """
    conn = get_conn()
    try:
        photo = doc_results.get("PHOTO") or {}
        id_doc = doc_results.get("ID") or {}
        letter = doc_results.get("LETTER") or {}

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO submissions
                   (course_id, submitted_at, email, form_data,
                    photo_valid, photo_result, id_valid, id_result, letter_valid, letter_result)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    course_id,
                    datetime.utcnow().isoformat(),
                    email,
                    Json(form_data),
                    1 if photo.get("valid") else (0 if photo else None),
                    Json(photo.get("result")) if photo.get("result") else None,
                    1 if id_doc.get("valid") else (0 if id_doc else None),
                    Json(id_doc.get("result")) if id_doc.get("result") else None,
                    1 if letter.get("valid") else (0 if letter else None),
                    Json(letter.get("result")) if letter.get("result") else None,
                )
            )
            sid = cur.fetchone()["id"]
        conn.commit()
        logger.info(f"Saved submission id={sid} for course_id={course_id}, email={email}")
        return sid
    finally:
        conn.close()


def get_submissions_by_course(course_id):
    """Return all submissions for a course, newest first."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM submissions WHERE course_id = %s ORDER BY id DESC",
                (course_id,)
            )
            rows = cur.fetchall()
        return [_parse_submission_row(row) for row in rows]
    finally:
        conn.close()


def get_submission_count(course_id):
    """Return submission count for a course."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM submissions WHERE course_id = %s",
                (course_id,)
            )
            row = cur.fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def update_submission_files(submission_id, file_keys):
    """
    Update file storage keys for a submission after finalization.
    file_keys: dict like {"PHOTO": "course-slug/42/PHOTO.jpg", "ID": "course-slug/42/ID.pdf"}
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE submissions SET photo_file=%s, id_file=%s, letter_file=%s WHERE id=%s""",
                (
                    file_keys.get("PHOTO"),
                    file_keys.get("ID"),
                    file_keys.get("LETTER"),
                    submission_id,
                )
            )
        conn.commit()
        logger.info(f"Updated file keys for submission id={submission_id}")
    finally:
        conn.close()


def get_submission_by_id(submission_id):
    """Return a single submission by id."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM submissions WHERE id = %s", (submission_id,))
            row = cur.fetchone()
        return _parse_submission_row(row) if row else None
    finally:
        conn.close()


def delete_submission(submission_id):
    """Delete a single submission."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM submissions WHERE id = %s", (submission_id,))
        conn.commit()
        logger.info(f"Deleted submission id={submission_id}")
    finally:
        conn.close()


def _parse_submission_row(row):
    """Convert a submission db row to a dict. JSONB columns are already decoded."""
    if row is None:
        return None
    d = dict(row)
    if d.get("form_data") is None:
        d["form_data"] = {}
    return d


# ============================================================================
# USER CRUD
# ============================================================================

def get_user_by_username(username):
    """Return a user by username (includes password_hash for login verification)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id):
    """Return a user by id (excludes password_hash)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, role, created_at, created_by FROM users WHERE id = %s",
                (user_id,)
            )
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_users():
    """Return all users (excludes password_hash)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, role, created_at, created_by FROM users ORDER BY id"
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_user(username, password_hash, role, created_by=None):
    """Create a new user. Returns user id."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users (username, password_hash, role, created_at, created_by)
                   VALUES (%s, %s, %s, %s, %s)
                   RETURNING id""",
                (username, password_hash, role, datetime.utcnow().isoformat(), created_by)
            )
            uid = cur.fetchone()["id"]
        conn.commit()
        logger.info(f"Created user '{username}' (id={uid}, role={role})")
        return uid
    finally:
        conn.close()


def update_user_role(user_id, new_role):
    """Update a user's role."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET role = %s WHERE id = %s", (new_role, user_id))
        conn.commit()
        logger.info(f"Updated role for user id={user_id} to {new_role}")
    finally:
        conn.close()


def update_user_password(user_id, new_password_hash):
    """Update a user's password."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (new_password_hash, user_id)
            )
        conn.commit()
        logger.info(f"Updated password for user id={user_id}")
    finally:
        conn.close()


def delete_user(user_id):
    """Delete a user."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        logger.info(f"Deleted user id={user_id}")
    finally:
        conn.close()


# ============================================================================
# NOTIFICATION CRUD
# ============================================================================

def create_notification(submission_id, doc_type, reason, admin_message, deadline, token, created_by):
    """Create a notification record. Returns notification id."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO notifications
                   (submission_id, doc_type, reason, admin_message, deadline, token, created_by, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (submission_id, doc_type, reason, admin_message, deadline, token,
                 created_by, datetime.utcnow().isoformat())
            )
            nid = cur.fetchone()["id"]
        conn.commit()
        logger.info(f"Created notification id={nid} for submission={submission_id}, doc={doc_type}")
        return nid
    finally:
        conn.close()


def get_notification_by_token(token):
    """Return notification joined with submission and course data for re-upload page."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT n.*, s.email, s.form_data, s.course_id,
                          c.name AS course_name, c.slug AS course_slug, c.doc_config
                   FROM notifications n
                   JOIN submissions s ON s.id = n.submission_id
                   JOIN courses c ON c.id = s.course_id
                   WHERE n.token = %s""",
                (token,)
            )
            row = cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        if d.get("form_data") is None:
            d["form_data"] = {}
        if d.get("doc_config") is None:
            d["doc_config"] = {}
        return d
    finally:
        conn.close()


def mark_notification_sent(notification_id):
    """Mark notification email as sent."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE notifications SET email_sent_at=%s, email_status='sent' WHERE id=%s",
                (datetime.utcnow().isoformat(), notification_id)
            )
        conn.commit()
    finally:
        conn.close()


def mark_notification_failed(notification_id):
    """Mark notification email as failed."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE notifications SET email_status='failed' WHERE id=%s",
                (notification_id,)
            )
        conn.commit()
    finally:
        conn.close()


def mark_token_used(notification_id):
    """Mark a re-upload token as used."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE notifications SET token_used=1 WHERE id=%s",
                (notification_id,)
            )
        conn.commit()
    finally:
        conn.close()


def get_notifications_for_submission(submission_id):
    """Return all notifications for a submission, newest first."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT n.*, u.username AS created_by_username
                   FROM notifications n
                   LEFT JOIN users u ON u.id = n.created_by
                   WHERE n.submission_id = %s
                   ORDER BY n.created_at DESC""",
                (submission_id,)
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_notifications_for_course(course_id):
    """Return all notifications for submissions in a course (for badge display)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT n.submission_id, n.doc_type, n.token_used,
                          n.email_sent_at, n.email_status, n.created_at
                   FROM notifications n
                   JOIN submissions s ON s.id = n.submission_id
                   WHERE s.course_id = %s
                   ORDER BY n.created_at DESC""",
                (course_id,)
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ============================================================================
# REUPLOAD LOG CRUD
# ============================================================================

def save_reupload_log(notification_id, submission_id, doc_type, new_valid, new_result, new_file):
    """Log a re-upload attempt."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO reupload_log
                   (notification_id, submission_id, doc_type, new_valid, new_result, new_file, uploaded_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (notification_id, submission_id, doc_type, new_valid,
                 Json(new_result) if new_result else None,
                 new_file, datetime.utcnow().isoformat())
            )
        conn.commit()
        logger.info(f"Logged re-upload for notification={notification_id}, doc={doc_type}")
    finally:
        conn.close()


def update_submission_doc(submission_id, doc_type, valid, result, file_key):
    """Update a specific document's validation result and file on a submission."""
    col_prefix = doc_type.lower()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE submissions SET {col_prefix}_valid=%s, {col_prefix}_result=%s, {col_prefix}_file=%s WHERE id=%s",
                (1 if valid else 0,
                 Json(result) if result else None,
                 file_key, submission_id)
            )
        conn.commit()
        logger.info(f"Updated submission={submission_id} doc={doc_type} valid={valid}")
    finally:
        conn.close()
