# SCOLIQ AI

**A configurable school attendance management platform**

SCOLIQ AI is a web-based attendance platform designed to make school and college attendance more organized, accessible, and easier to manage. It brings key school-level workflows into one Principal dashboard and gives teachers a dedicated workspace for their assigned classes.

The project is intended to be reusable by different schools and colleges. Each institution can deploy its own isolated installation, connect its own PostgreSQL/Supabase database, and customize the platform's school identity and visual appearance.

> **Deployment model:** SCOLIQ AI currently uses a separate application deployment and database for each school. It is not one centrally hosted, shared multi-school SaaS database. A school adopting the project deploys its own instance and manages its own data and configuration.

---

## Why I am building it

Traditional attendance workflows can involve disconnected records, manual coordination, and limited visibility for school leadership. SCOLIQ AI aims to bring these workflows into a single online system so that:

- The Principal can oversee the school's classes, teachers, students, and attendance from one dashboard.
- Teachers can manage their assigned class workflows from a dedicated portal.
- Attendance can be recorded, reviewed, corrected where authorized, and finalized through a consistent process.
- School information and visual identity can be configured for each institution.
- The platform can be deployed by other schools and colleges, not only the institution where the project idea was first developed.

## Main capabilities

### Principal portal

- School-level dashboard and attendance overview.
- Review, approve, or reject teacher access requests.
- Manage teacher status and class assignments.
- View and manage class and student records.
- Review guardian-consent status for face enrollment.
- Monitor live attendance sessions and review finalized attendance reports.
- Access audit and security-related views.
- Configure the school's name, logo URL, and supported visual-branding options through **Brand Studio**.

### Teacher portal

- Submit an access request and follow its approval/activation status.
- Activate an approved account and use WebAuthn passkeys for supported sign-in flows.
- Set up or work with assigned classes and student rosters.
- View student and consent-related status.
- Record attendance, review the session, confirm student statuses, and finalize the attendance workflow.
- View attendance history and manage passkeys.

### Attendance workflow

- Supports manual attendance as the baseline mode.
- Uses a review-and-confirm workflow rather than treating an uncertain scan as a final attendance decision.
- Supports correction and finalization controls with role checks and audit records.
- Includes an optional face-provider integration path. Face matching is not required for the platform's manual attendance workflow.

### School-specific branding

Every school can configure its own identity within its separate installation. The Brand Studio supports validated presentation settings such as:

- School name and optional school code.
- A school-hosted logo URL.
- Basic, Clean, and Premium visual profiles.
- Light, dark, or system appearance.
- Primary and accent colors.
- Supported sidebar, card, layout, density, radius, masthead, and logo-placement options.

Branding is stored as school profile data in the database and is shared across the Principal portal, Teacher portal, and public sign-in/activation screens. The platform accepts a hosted logo URL; it does not provide a logo file-upload service in the current implementation.

---

## Technology stack

| Area | Technology |
|---|---|
| Backend API | Python, FastAPI, Uvicorn |
| Frontend | React, TypeScript, Vite |
| Database access | SQLAlchemy 2.x, Psycopg 3 |
| Database migrations | Alembic |
| Database | PostgreSQL; Supabase PostgreSQL can be used as the hosted database |
| Authentication and sessions | Argon2id, server-side sessions, cookie/CSRF controls |
| Teacher authentication | WebAuthn passkeys |
| Face processing integration | OpenCV-based detection/provider adapters and ONNX Runtime integration |
| Testing | Pytest, HTTPX, and frontend Vitest test files |
| Deployment packaging | Docker and Render blueprint configuration |

The frontend is built into static assets and served by FastAPI in the same-origin production setup. During local development, Vite provides the frontend development server and proxies API requests to FastAPI.

## Security and privacy approach

SCOLIQ AI is intended for a school environment and may handle information about minors. Privacy and consent must therefore be treated as core operational requirements, not optional extras.

The current implementation includes controls such as:

- Role-checked backend endpoints for Principal and Teacher actions.
- Argon2id password hashing and server-side session handling.
- WebAuthn challenge and origin checks for passkey flows.
- CSRF and secure-cookie configuration options.
- Guardian-consent gating for face enrollment.
- AES-GCM encryption for stored face templates.
- Deletion of active face templates when consent is withdrawn.
- Teacher review and manual confirmation so an uncertain face result does not automatically decide a student's attendance status.
- A backend-only database connection model; database credentials are not intended for browser code.

**Important:** These implementation controls do not constitute a penetration test, legal-compliance certification, or guarantee of biometric accuracy. A school must review applicable child-privacy requirements, its own policies, parental/guardian permission, retention and deletion procedures, and an equivalent non-biometric attendance option before using face-related features with real students.

### Face recognition status

Manual attendance is the default configuration (`FACE_PROVIDER=manual`). The repository contains optional face-processing integration code and model artifacts, but enabling face recognition for real attendance requires a separate review of model provenance and licensing, correct deployment configuration, threshold calibration, device and camera testing, privacy approval, and performance testing on the actual hosting plan.

The project does **not** claim certified liveness detection, anti-spoofing, or guaranteed identification accuracy. A face match should not be treated as proof of identity or as a substitute for teacher review.

---

## Repository layout

```text
SmartAttend-AI/
├── app/                 # FastAPI application, APIs, auth, face and services
├── frontend/            # React + TypeScript + Vite application
├── alembic/             # Database migration environment and revisions
├── models/face/         # Face detector / embedding model artifacts
├── sql/                 # Supabase runtime-role and database access SQL
├── scripts/             # Model/runtime verification utilities
├── tests/               # Backend and integration tests
├── docs/                # OpenAPI JSON reference
├── Dockerfile
├── docker-compose.yml
├── render.yaml
├── requirements.txt
├── requirements-prod.txt
└── README.md
```

## Run locally

### Requirements

- Python 3.11–3.13 (the project metadata supports this range; Python 3.12 is a suitable target).
- Node.js 22.12 or later and npm.
- Git.
- Docker Desktop or another Docker-compatible runtime for local PostgreSQL.

### Backend — Windows PowerShell

```powershell
# Enter the project directory.
cd SmartAttend-Ai

# Create and activate a virtual environment.
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install Python dependencies.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Start the local PostgreSQL service (host port 54329).
docker compose up -d postgres

# Create your local environment file and generate secrets.
Copy-Item .env.example .env
python -m app.cli generate-secrets
```

Copy the generated values into `.env` for `SESSION_SECRET`, `INITIAL_ADMIN_SETUP_TOKEN`, and `FACE_TEMPLATE_ENCRYPTION_KEY`. Keep `.env` private and never commit real secret values.

```powershell
# Apply database migrations.
alembic upgrade head

# Create the first Principal account.
python -m app.cli create-admin

# Start the API server.
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend — second terminal

```powershell
cd frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

Open the local Vite address shown in the terminal. The Principal portal is available at `/admin`, and the Teacher portal is available at `/teacher`.

For macOS/Linux, use `python3.12 -m venv .venv`, activate with `source .venv/bin/activate`, and copy environment files with `cp` instead of `Copy-Item`.

### Useful local endpoints

- API documentation: `http://127.0.0.1:8000/api/v1/docs`
- Liveness check: `http://127.0.0.1:8000/health/live`
- Readiness check: `http://127.0.0.1:8000/health/ready`

---

## Deployment model: Render + Supabase

The repository includes a Dockerfile and `render.yaml` for a Render web service. Each adopting school should create and manage its own Render service and Supabase project.

The backend connects to Supabase through PostgreSQL using SQLAlchemy. The standard application database path does **not** require a Supabase Project URL plus a Supabase `service_role` key.

Configure the relevant Render environment variables using the actual values for the school's deployment:

| Variable | Purpose |
|---|---|
| `APP_ENV` | Set to `production`. |
| `APP_BASE_URL` | Public base URL for the school's application. |
| `DATABASE_URL` | PostgreSQL connection string for the restricted `smartattend_runtime` database role. |
| `MIGRATION_DATABASE_URL` | Schema-owner connection used by Alembic migrations. |
| `SESSION_SECRET` | Unique, strong session secret. |
| `INITIAL_ADMIN_SETUP_TOKEN` | One-time bootstrap secret for initial Principal setup. |
| `FACE_TEMPLATE_ENCRYPTION_KEY` | Separate base64-encoded 32-byte key for face-template encryption. Keep it protected and backed up securely. |
| `COOKIE_SECURE` | `true` in production. |
| `COOKIE_SAMESITE` | Usually `lax` for the same-origin deployment. |
| `WEBAUTHN_RP_ID` | The final application hostname, without the scheme. |
| `WEBAUTHN_ORIGIN` | Exact HTTPS origin used by the Teacher portal. |
| `CORS_ALLOWED_ORIGINS` | Exact allowed frontend origin(s), formatted as the application's expected JSON array. |
| `SCHOOL_TIMEZONE` | School's IANA timezone; `Asia/Kolkata` is the default in the blueprint. |
| `FACE_PROVIDER` | Keep `manual` until optional face processing has passed its separate readiness checks. |

The SQL file `sql/supabase_runtime_role.sql` is provided to create a restricted backend runtime role and configure the intended database grants/RLS policy. Review it and replace its placeholder password before running it as the database owner. Use the runtime role for `DATABASE_URL`; reserve the schema-owner connection for migrations. URL-encode special characters in PostgreSQL connection-string passwords.

The Render blueprint includes `alembic upgrade head` as a pre-deploy command. Confirm that the selected Render service plan supports the configured pre-deploy workflow. Set the WebAuthn RP ID and origin to the final stable domain before teachers register passkeys.

**Never place database passwords, `service_role` keys, session secrets, bootstrap tokens, or encryption keys in frontend `VITE_*` variables or committed files.** Do not use the database owner credential as the app's normal runtime credential.

No Render or Supabase deployment is claimed by the checked-in verification report. A successful local test is not proof that a cloud deployment, its database permissions, or its chosen hosting capacity has been validated.

---

## Tests and current verification status

The latest verification report included in the supplied project archive is dated **November 9, 2026**. It records the following:

| Check | Recorded result |
|---|---|
| Python compilation | Passed |
| Backend automated tests | **33 passed, 1 skipped** |
| Backend coverage run | 69.78% total coverage; one non-failing SQLite `ResourceWarning` was reported |
| Fresh SQLite Alembic migrations | Passed |
| Uvicorn smoke test and health endpoints | Passed |
| OpenAPI endpoint | Passed; snapshot contained 53 paths |
| TypeScript/TSX parser and relative-import inspection | Passed for 15 source files; this was syntax/import inspection only |
| PostgreSQL integration test | Skipped because a dedicated `TEST_POSTGRES_URL` was not available |
| Frontend dependency installation, production build, and Vitest suite | Not completed in that environment because npm registry access failed |
| Docker image build | Not run in that environment |
| Real browser WebAuthn ceremony | Not verified |
| Real face-model inference and production threshold calibration | Not verified |
| Render + Supabase deployment | Not performed |

Before a real school pilot, run the frontend build and tests in a networked environment, execute PostgreSQL integration tests against a dedicated test database, validate the actual Render/Supabase configuration, and complete security, privacy, consent, backup/restore, and load testing.

Useful commands:

```bash
# Backend tests
python -m pytest -q

# Frontend build and tests
cd frontend
npm install
npm run build
npm test
```

---

## About the creator

**Ramu Jaiswal**, known online as **Mahesh Editor**, is the creator of SCOLIQ AI. He is a **Class XI-B2** student at **Shree Gandhi Smarak Inter College, Hata, Uttar Pradesh, India**, and has around **three years of video-editing experience**.

His learning approach is self-directed: he explores topics through AI tools, internet research, practical experiments, testing, and iteration. He is interested in adapting his skills across multiple domains, building useful products, and contributing in the long term to India's progress in advanced AI and AGI technologies.

He has also launched **AttachAi Assistant**, a separate platform designed to provide customizable AI assistants for websites.

### How this project was created

SCOLIQ AI is an independently guided, AI-assisted project. The initial idea, problem selection, product direction, and intended outcomes came from Ramu Jaiswal. He uses AI as a development collaborator to help refine raw ideas into requirements, plan architecture, understand implementation steps, develop prompts, generate and revise code, investigate errors, and improve the system through repeated testing and feedback.

**ChatGPT contributed substantially** to clarifying the concept, shaping the architecture, prompt engineering, coding assistance, debugging, and iterative implementation. Ramu guided the work, explored and tested the results, identified issues and gaps, and directed further improvements. The project is not presented as work completed by a human development team; its workflow is centered on the creator working with AI tools.

---

## Project links

- **GitHub repository:** [theindiaaiofficial/SmartAttend-Ai](https://github.com/theindiaaiofficial/SmartAttend-Ai)

## License

No `LICENSE` file was present in the supplied project archive. A public GitHub repository is not automatically an open-source license grant. Add a license file if you intend to permit reuse, modification, or redistribution under specific terms.

---

*SCOLIQ AI — making school attendance more organized, adaptable, and accessible.*
