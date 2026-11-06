# CLAUDE.md — SalomatOS Backend

Multi-tenant SaaS for dental clinics. Django 6 + DRF, PostgreSQL. The frontend is a
separate repo (`salomatos-v2-frontend`) served same-origin under `/api/*`.

**Data type: PHI (personal health information).** Every decision follows from that.
P0 rules below are never broken, even on request: say which rule, offer a safe alternative.

## P0 — Security and PHI

- **Tenant = `tenancy.Clinic`.** Every clinical or business row has a `clinic` FK.
  The clinic comes from the `X-Clinic-Id` header plus the caller's `Membership`,
  never from the body or the user row.
- **Every tenant endpoint extends `ClinicScopedMixin`** (`apps/tenancy/viewsets.py`),
  listed first in the class bases. Its `get_queryset` filters by clinic;
  `scope_queryset` may only narrow it.
- **Every FK input uses `ClinicRelatedField`** (`apps/tenancy/fields.py`). A plain
  `PrimaryKeyRelatedField` accepts ids from other tenants.
- **Records hung off a patient call `ensure_patient_visible`** and filter with
  `patient_filter` (`apps/patients/access.py`).
- **Permissions live in `apps/tenancy/permissions.py`.** Each view maps every action
  to a permission in `required_permissions`; an unmapped action is denied.
  `/api/v1/auth/me/` returns the permission list, so the frontend never hardcodes roles.
- **"All branches" mode** (`X-Organization-Id`) is for organization owners and only
  for the read actions a view lists in `organization_actions`. Writes need one clinic.
- **No PHI in URLs.** Text search is `POST .../search/` with a body. UUID ids only.
- **No PHI in logs, errors or `__str__`.** Model `__str__` returns the id. The 500
  handler returns a generic message. File names are random; download names use ids.
- **Uploaded files are private.** No `media/` URL exists; files stream through
  authenticated `download` actions. Do not add a static/media route.
- **Patients are never deleted** (archive/restore). Clinical FKs to `Patient` use `PROTECT`.
- **Audit**: reads and writes of PHI go to `audit.AuditLog` (ids only, append-only).
- **No `AllowAny`** except login and token refresh. A new public endpoint = stop and ask.
- No secrets in the repo; settings come from env (`.env.example`). `DEBUG` defaults to off.

## Layout

```
apps/core        BaseModel (UUID pk, timestamps), validators (phone, FDI tooth), exceptions
apps/accounts    User (staff login only), auth views: login, refresh, logout, me
apps/tenancy     Organization, Clinic, Membership, Specialty; scoping, permissions, staff
apps/audit       AuditLog
apps/patients    Patient, MedicalHistory
apps/catalog     ServiceCategory, Service (price list)
apps/scheduling  Chair, Appointment (doctor/chair conflict check)
apps/clinical    Prescription, PrescriptionItem, PDF
apps/imaging     Attachment (X-ray, photo) with private download
apps/dental      ToothRecord + ToothEvent (chart, FDI), TreatmentPlan + PlanItem, Procedure
apps/billing     Payment (manual entry: cash/card/transfer), patient balance and debtors
```

- **Money is append-only.** Procedures and payments are never edited or deleted;
  a mistake is voided with a reason (`void` action). Prices are copied onto the
  line when it is created, so price list changes never rewrite history.

Patients do not log in. They will reach their data only through the Telegram bot
(planned), which must authenticate with a one-time link code, never by phone number.

## Workflow

```bash
python manage.py makemigrations --check --dry-run
ruff format --check . && ruff check .
python manage.py spectacular --validate --fail-on-warn --file /tmp/schema.yml
SECURE_SSL_REDIRECT=0 pytest      # all green before saying "done"
python manage.py seed_demo        # local demo data, DEBUG only
```

- A new tenant endpoint ships with an isolation test (other clinic -> 404, foreign
  FK -> 400, role without permission -> 403). See `tests/test_tenant_isolation.py`.
- Code, comments, commits and PRs in English. Comments explain why, not what.
- Do not merge PRs and do not push to `main`.
