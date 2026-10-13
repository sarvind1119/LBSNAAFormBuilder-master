# LBSNAA Form Builder

A Flask-based course registration platform with:

- Admin dashboard to create, duplicate and manage course-specific forms
- Public registration forms (`/form/<slug>`) for participants
- AI-assisted document validation for `PHOTO`, `ID`, and `LETTER`
- PostgreSQL for courses, submissions and users; Azure Blob Storage for uploaded documents
- Multi-user admin with per-course access (manager / viewer)
- Document re-upload requests by email, CSV export and bulk attachment download
- Optional celebrity face detection for uploaded photos

---

## Table of Contents

- Overview
- Features
- Architecture
- Project Structure
- How It Works
- Prerequisites
- Run Locally (Docker Compose)
- Run Locally (Python)
- Environment Variables
- Admin Workflows
- API Endpoints
- Database Schema
- AI Validation Pipeline
- Deployment (Azure)
- Troubleshooting
- Security Notes
- Roadmap Ideas

---

## Overview

This project helps teams run course/event registrations where each course can define:

- Which participant fields are shown and required (including custom fields)
- Which documents are required
- Whether registrations are open/closed

Participants submit forms through a public URL. Each uploaded document is checked by the
validation model as it is uploaded. Participants may submit even if a document is rejected
(the model is still being trained and can make mistakes); admins see the model's verdict for
every document and can request a re-upload or replace the file themselves.

---

## Features

### Admin

- User accounts with roles:
  - **Global admin**: all courses, course setup, user management
  - **Per-course user**: per course, either **manager** (flag/notify, replace documents, delete submissions) or **viewer** (read-only)
- Create, edit, **duplicate**, open/close and delete courses
- Configure default fields (labels editable, enable/require) and custom fields
  (`text`, `email`, `tel`, `date`, `time`, `textarea`, `select`)
- Configure document types (`PHOTO`, `ID`, `LETTER`): enabled, required, label
- View submissions with per-document verdict, confidence and name-match details
- Flag a document and email the participant a single-use re-upload link (single or bulk)
- Replace a document on a submission (re-validated automatically)
- Export submissions as CSV; download all attachments for a course as a ZIP
- Change own password

### Public Form

- Dynamic fields rendered from course configuration
- Drag-and-drop document upload with instant validation feedback
- Client- and server-side validation (required fields, email, 10-digit mobile)
- Rejected documents can still be submitted; required documents must be uploaded
- One registration per email per course (case-insensitive)

### AI Validation

- Type classification using a pre-trained ML model
- Outlier detection (invalid/suspicious files)
- PDF-to-image conversion + best-page selection
- OCR extraction for ID/LETTER documents
- OCR-assisted correction for misclassification edge cases
- Name matching against OCR text (for ID/LETTER)
- Optional LLM fallback for OCR extraction (OpenAI)
- Optional celebrity face detection for PHOTO uploads

---

## Architecture

1. Flask app (`app.py`) serves the admin UI, public UI and APIs; run by gunicorn in production (`wsgi.py`).
2. PostgreSQL (`database.py`) stores courses, submissions, users, access rights, notifications and audit logs.
3. Azure Blob Storage (`storage.py`) stores uploaded documents (Azurite emulator locally).
4. `ModelManager` loads and caches ML artifacts on startup.
5. `validation_engine.py` executes the document validation pipeline.
6. `celebrity_detection.py` (optional) checks uploaded faces against a reference dataset.
7. `email_service.py` sends re-upload notification emails over SMTP.
8. Frontend JS (`static/form.js`, `static/reupload.js`, `static/admin.js`) drives client behavior.

---

## Project Structure

```text
LBSNAAFormBuilder/
  app.py                  # routes, auth, validation API, admin + public views
  wsgi.py                 # gunicorn entry point (initializes DB + models)
  database.py             # PostgreSQL schema + queries
  storage.py              # Azure Blob Storage backend
  email_service.py        # SMTP re-upload notifications
  validation_engine.py
  model_manager.py
  celebrity_detection.py
  requirements.txt
  Dockerfile
  docker-compose.yml      # app + PostgreSQL + Azurite
  .github/workflows/deploy.yml
  models/
    document_classifier.pkl
    outlier_detector.pkl
    feature_names.pkl
    celebrity_embeddings.pkl
  celebrity_reference/
    <celebrity folders with images>
  static/
    admin.js
    form.js
    reupload.js
  templates/
    admin/
    public/
    base.html
  temp_uploads/           # short-lived files during validation
```

---

## How It Works

### 1. Startup

- Creates PostgreSQL tables if missing (no migration tool; `init_db()` is idempotent)
- Seeds the `admin` user (password from `ADMIN_PASSWORD`) if there are no users. In production
  no admin is created when `ADMIN_PASSWORD` is unset (development falls back to `admin`)
- Loads ML models from `models/` and the optional celebrity detector
- Cleans up pending uploads and verdicts older than `UPLOAD_CLEANUP_HOURS`

### 2. Admin Configures a Course

- Sets course name, slug (public URL), description
- Enables/disables and relabels default fields, adds custom fields
- Enables/disables document types and marks them required
- Or duplicates an existing course (see Admin Workflows)

### 3. Participant Submits Form

- Opens `/form/<slug>`, fills fields, uploads documents
- Each upload goes to `POST /api/validate/<doc_type>`. The server stores the file in pending
  blob storage **and records the model's verdict** (`pending_validations`) for the browser's
  upload session
- Final submission goes to `POST /form/<slug>/submit`. The server uses the verdicts it
  recorded (never values sent by the browser), moves files to permanent storage, and saves
  the submission

### 4. Admin Reviews Data

- Views submissions and per-document verdicts
- Flags documents and emails re-upload links, or replaces documents directly
- Exports CSV / downloads attachments ZIP

---

## Prerequisites

- Python 3.10 (matches the Docker image)
- PostgreSQL (16 used in Docker Compose; the `citext` extension is created automatically)
- Azure Blob Storage, or the Azurite emulator for local development
- System packages for OCR/PDF/image processing:
  - Tesseract OCR, Poppler utilities (for `pdf2image`), OpenCV runtime libraries
  - Debian/Ubuntu: `tesseract-ocr poppler-utils libgl1 libglib2.0-0`
- Windows: the code tries common Tesseract install paths automatically; if not found, OCR for ID/LETTER degrades.

---

## Run Locally (Docker Compose)

Recommended: starts the app, PostgreSQL and the Azurite blob emulator.

```bash
docker compose up --build
```

- App: `http://localhost:5000` (admin login: `admin` / `admin` as set in `docker-compose.yml`)
- PostgreSQL: `localhost:5432` (`admin` / `testpass`, database `lbsnaa`)
- Azurite blob endpoint: `localhost:10000`
- `models/` and `celebrity_reference/` are mounted read-only from the host
- Put secrets (`OPENAI_API_KEY`, `SMTP_*`) in a `.env` file next to `docker-compose.yml`; never commit it

---

## Run Locally (Python)

1. Start PostgreSQL and Azurite (for example `docker compose up -d db azurite`).

2. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

3. Set environment variables (PowerShell example):

```powershell
$env:DATABASE_URL="postgresql://admin:testpass@localhost:5432/lbsnaa"
$env:AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://localhost:10000/devstoreaccount1;"
$env:ADMIN_PASSWORD="change-me"
$env:SECRET_KEY="change-this-secret"
$env:FLASK_ENV="development"   # enables Flask debug mode; never set this in production
```

4. Start the development server:

```bash
python app.py
```

5. Open the admin login at `http://localhost:5000/admin/login` and the health check at `http://localhost:5000/health`.

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql://admin:testpass@localhost:5432/lbsnaa` | PostgreSQL connection string |
| `AZURE_STORAGE_CONNECTION_STRING` | unset (required for uploads) | Azure Blob Storage / Azurite connection string |
| `BLOB_CONTAINER_NAME` | `uploads` | Blob container for documents (created if missing) |
| `SECRET_KEY` | random per start (production) / `dev-secret-change-me` (development) | Flask session signing key — **set in production**, otherwise everyone is logged out on each restart |
| `ADMIN_PASSWORD` | unset (production) / `admin` (development) | Password for the seeded `admin` user (only used when no users exist) |
| `FLASK_ENV` | `production` | Set to `development` to enable debug mode with `python app.py` |
| `SESSION_COOKIE_SECURE` | `1` (production) / `0` (development) | Send the session cookie over HTTPS only. Set to `0` only when serving production mode over plain HTTP locally |
| `TRUST_PROXY` | `1` | Trust one proxy hop of `X-Forwarded-For/Proto/Host` (Azure front end) for client IP and scheme. Set to `0` if the app is exposed directly |
| `CORS_ORIGINS` | unset | Comma-separated origins allowed to call the app cross-origin; unset = same-origin only |
| `PORT` | `5000` | Port for `python app.py` and the gunicorn container |
| `BASE_URL` | request host | Public base URL used in re-upload email links |
| `SMTP_HOST` | unset | SMTP server; email notifications are disabled when unset |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | unset | SMTP credentials |
| `SMTP_USE_TLS` | `true` | Use STARTTLS |
| `SMTP_FROM_EMAIL` | `noreply@lbsnaa.gov.in` | Sender address |
| `SMTP_FROM_NAME` | `LBSNAA Form Builder` | Sender name |
| `UPLOAD_CLEANUP_HOURS` | `24` | Age after which unsubmitted uploads and verdicts are removed at startup |
| `OPENAI_API_KEY` | unset | Enables LLM OCR fallback in the validation engine |

---

## Admin Workflows

### Course Configuration

Default fields are pre-seeded: Name, Email, iNomination Number, Gender, Job Title, Service,
Batch, Cadre, Zone, State, Department, Mobile.

- `name` and `email` are always enabled and required (labels can still be edited)
- Service, Cadre, Zone and State use predefined option lists
- Custom fields are keyed by their label (e.g. "Current Posting" → `current_posting`)

### Duplicating a Course

Use **Duplicate** on the dashboard (global admins) to start a new course from an existing one,
for example the next batch of a recurring programme.

- Opens the new-course form pre-filled with the original's name ("… (Copy)"), slug
  (`<slug>-copy`), description, all default/custom field settings and document settings
- Nothing is created until you click **Create Copy**
- The copy starts **closed**; click **Activate** when ready
- Submissions and per-course user access are **not** copied

### Reusing a Published Link (Link Handover)

When a link such as `/form/ai-champions2026` has already been shared and the next batch should
register on the same URL, tick **Keep the same public link** on the Duplicate page:

- Enter a new link for the old course, e.g. `ai-champions2026-round3`
- On **Create Copy**, in a single transaction:
  - the old course moves to the new link and is **closed** — its submissions, exports, attachments and re-upload links keep working
  - the new course takes over the original link and is **open immediately**
- Participants of the old course can register again, because the one-per-email rule is per course

### Users and Access

- **Users → New User**: choose Global Admin, or Per-course User and set manager/viewer per course
- Role changes and deletions take effect on the user's next request
- Users cannot delete their own account

### Submission Review and Follow-up

- Submissions table with configurable columns; expand a row for document previews, confidence and name-match details
- **Flag & Notify**: pick a document, write a message and a deadline; the participant gets an
  email with a single-use re-upload link (`/reupload/<token>`), valid through the end of the
  deadline date (IST). Requires SMTP configuration. Bulk flagging is available for selected submissions
- **Replace document**: managers/admins upload a new file for a submission; it is re-validated and logged
- **Notification history** per submission (audit trail)
- **Export CSV** and **Download attachments** (ZIP, one folder per participant)

---

## API Endpoints

### Public

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | App status and model readiness |
| `GET` | `/form/<slug>` | Registration form (or "closed" page) |
| `POST` | `/api/validate/<doc_type>` | Validate one document (`ID`, `PHOTO`, `LETTER`); rate-limited 30/min |
| `POST` | `/form/<slug>/submit` | Submit a registration |
| `GET` | `/reupload/<token>` | Re-upload page from a notification email |
| `POST` | `/api/reupload/<token>` | Upload the replacement document; rate-limited 10/min |

`POST /api/validate/<doc_type>` — multipart form:

- `file` (required): `jpg`, `jpeg`, `png`, `pdf`, `webp`, `bmp`, `tiff`, `tif`, `gif`; max 5 MB
- `name` (optional): participant name, improves OCR name matching
- `upload_session_id` (optional): random id generated by the form page; when present the file
  and the verdict are kept for the final submission

Response: `status` and `validation` (`is_valid`, `result`, `confidence`, `message`, OCR details,
name match, celebrity warning).

`POST /form/<slug>/submit` — JSON body:

- `form_data`: object of field key → string value
- `upload_session_id`: the id used for uploads

Returns `201` with `submission_id`; `400` for missing/invalid fields or a missing required
document; `409` if the email (case-insensitive) already registered for the course. Any
`doc_results` sent by the client are ignored.

### Admin (session login required)

Courses: `/admin`, `/admin/course/new`, `/admin/course/<id>/edit`, `/admin/course/<id>/duplicate`,
`/admin/course/<id>/toggle`, `/admin/course/<id>/delete`, `/admin/course/<id>/submissions`,
`/admin/course/<id>/export`, `/admin/course/<id>/download-attachments`.

Submissions: `/admin/submission/<id>/file/<doc_type>`, `/admin/submission/<id>/delete`,
`/admin/submission/<id>/flag-notify`, `/admin/submission/<id>/replace-doc/<doc_type>`,
`/admin/submission/<id>/notifications`, `/admin/submissions/bulk-flag-notify`.

Users: `/admin/users`, `/admin/users/new`, `/admin/users/<id>/edit`, `/admin/users/<id>/delete`,
`/admin/change-password`, `/admin/login`, `/admin/logout`.

---

## Database Schema

PostgreSQL, created by `init_db()` in `database.py`. JSON columns are `JSONB`; timestamps are
ISO-8601 text (UTC).

| Table | Purpose / key columns |
|---|---|
| `courses` | `id`, `name`, `slug` (unique), `description`, `fields_config`, `doc_config`, `is_active` (0/1), `created_at` |
| `submissions` | `id`, `course_id` → courses (cascade), `submitted_at`, `email`, `form_data`, `{photo,id,letter}_valid`, `{photo,id,letter}_result`, `{photo,id,letter}_file` (blob keys); unique `(course_id, email)` |
| `users` | `id`, `username` (`CITEXT`, unique), `password_hash`, `role` (`admin` / `viewer`), `created_at`, `created_by` |
| `user_course_access` | `(user_id, course_id)` PK, `role` (`manager` / `viewer`) |
| `pending_validations` | `(session_id, doc_type)` PK, `valid`, `result`, `created_at` — model verdicts between upload and submit |
| `notifications` | re-upload requests: `submission_id`, `doc_type`, `reason`, `admin_message`, `deadline`, `token` (unique), `token_used`, `email_status`, `created_by` |
| `reupload_log` | participant re-uploads per notification |
| `admin_doc_replacement` | documents replaced by admins/managers |
| `app_meta` | one-time migration markers |

Uploaded files are stored in Blob Storage as `_pending/<session>/<DOC>.<ext>` until submission,
then `<course-slug>/<submission-id>/<DOC>.<ext>`. Stored keys stay valid if a course's slug
changes later (e.g. after a link handover).

---

## AI Validation Pipeline

Implemented in `validation_engine.py`.

1. Accept image/PDF.
2. If PDF: convert pages to PNG, score pages by content + edge density, select the best page.
3. Reject blank/mostly white documents.
4. Preprocess image (resize, denoise, contrast normalization).
5. Extract features: aspect ratio, content density, edge density.
6. Run outlier detector.
7. Run classifier and confidence check.
8. For ID/LETTER:
   - OCR text extraction (`pytesseract`)
   - Optional LLM fallback (OpenAI) if OCR confidence is low
   - Name matching against the provided user name
   - ID pattern checks / letter keyword boosts in specific mismatch cases
9. For PHOTO: optional celebrity face comparison via InsightFace.

On the registration form, a document counts as accepted only when the result is `ACCEPT`;
other results (`SUSPICIOUS`, `MISMATCH`, `BLANK`, …) are stored as rejected for admin review.
Participant re-uploads and admin replacements store the engine's `is_valid` flag.

---

## Deployment (Azure)

- Pushing to `main` runs `.github/workflows/deploy.yml`: builds the image in Azure Container
  Registry, updates the App Service container, restarts it and checks `/health`.
  Step-by-step setup: `Azure_Deployment_StepByStep_Guide_1.md`.
- The container runs gunicorn (`wsgi:app`) with **one worker and four threads**, so models are
  loaded once and the in-memory rate limiter stays consistent. It listens on `$PORT`
  (default `5000`); if App Service routes to another port, set `WEBSITES_PORT=5000`.
- Configure in App Service settings: `DATABASE_URL`, `AZURE_STORAGE_CONNECTION_STRING`,
  `SECRET_KEY`, `ADMIN_PASSWORD` (first start only), `BASE_URL`, `SMTP_*`, optionally `OPENAI_API_KEY`.
- Do **not** set `FLASK_ENV=development` in production.
- Model files must exist at startup; missing models fail initialization.
- Schema changes are applied by `init_db()` on startup (`CREATE … IF NOT EXISTS`).

---

## Troubleshooting

### `503 Models not loaded`

- Verify `models/` contains `document_classifier.pkl` and `outlier_detector.pkl`
  (`feature_names.pkl` optional but recommended).

### App fails to start: database or storage errors

- Check `DATABASE_URL` is reachable and the user can create tables/extensions (`citext`).
- Check `AZURE_STORAGE_CONNECTION_STRING`; locally make sure Azurite is running.

### OCR returns empty/low confidence

- Confirm Tesseract is installed and accessible; improve image quality.
- Set `OPENAI_API_KEY` to enable the LLM fallback.

### PDF validation fails

- Install Poppler utilities and verify `pdf2image` is installed.

### Celebrity detection unavailable

- Install `insightface` + `onnxruntime`; ensure `celebrity_reference/` has at least 3 images per person.

### "Flag & Notify" says SMTP not configured

- Set `SMTP_HOST` (and credentials). Set `BASE_URL` so email links point to the public site.

### Participant sees "… must be uploaded" after uploading

- The upload was not recorded for their session (e.g. the page was open across a deployment,
  or validation failed). Re-uploading the document fixes it.

### Duplicate submission error (409)

- The same email (any letter case) already registered for this course.

---

## Security Notes

- Multi-user login with hashed passwords; role and per-course permissions are re-checked against the database on every admin request
- CSRF protection (Flask-WTF) on admin forms and actions; public JSON/upload endpoints are CSRF-exempt
- Passwords must be at least 8 characters (new users, admin resets and password changes)
- Session cookie is `HttpOnly`, `SameSite=Lax` and, in production, `Secure`
- No cross-origin access unless `CORS_ORIGINS` is set
- Rate limiting per client IP (taken from Azure's `X-Forwarded-For`): login 10/min,
  validation 30/min, re-upload 10/min, form submission 20/min
- No insecure fallbacks in production: a missing `SECRET_KEY` gets a random key (with a warning),
  and no `admin`/`admin` account is seeded without `ADMIN_PASSWORD`
- Deleting a submission or course also deletes its uploaded files from Blob Storage
- Security headers (CSP, `X-Frame-Options`, `nosniff`, referrer policy)
- Validation verdicts are recorded server-side; the browser cannot alter them
- Re-upload links are random, single-use and expire at the end of the deadline day (IST)

Operational notes:

- Enable **HTTPS Only** on the App Service so the `Secure` session cookie is always usable
- Rate limits are kept in memory per worker and reset on restart
- Existing passwords shorter than 8 characters keep working until they are changed

---

## Roadmap Ideas

- Add a test suite (unit + integration + API)
- Add a migration framework (Alembic or similar)
- Pin dependency versions for reproducible builds
- Connection pooling for PostgreSQL
- Async queue for heavy document validation workloads
- Observability dashboards and metrics
