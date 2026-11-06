# SalomatOS backend

Django + DRF API for the SalomatOS dental clinic platform. Rules for contributors
and agents: [CLAUDE.md](CLAUDE.md).

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # set SECRET_KEY
createdb salomatos_v2
python manage.py migrate
python manage.py seed_demo      # demo_owner / demo_admin1 / demo_doctor1, password printed
python manage.py runserver
```

API schema: `/api/schema/` (OpenAPI 3). Swagger UI at `/api/docs/` when `DEBUG=1`.

## API at a glance

All tenant endpoints need `Authorization: Bearer <access>` and `X-Clinic-Id: <clinic uuid>`.
Organization owners may send `X-Organization-Id` instead for read-only "all branches" lists.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/auth/login/`, `refresh/`, `logout/` | JWT session (`{"result": {access_token, refresh_token}}`) |
| `GET /api/v1/auth/me/` | User, clinics, permissions, owned organizations |
| `GET/PATCH /api/v1/clinic/` | Current clinic |
| `/api/v1/staff/`, `/specialties/` | Employees and their roles |
| `/api/v1/patients/` (+ `search/`, `archive/`, `restore/`, `medical-history/`) | Patients |
| `/api/v1/services/`, `/service-categories/` | Price list |
| `/api/v1/chairs/`, `/appointments/` | Schedule |
| `/api/v1/prescriptions/` (+ `pdf/`) | Prescriptions |
| `/api/v1/attachments/` (+ `download/`) | X-rays and photos |
| `/api/v1/tooth-records/` (+ `history/`) | Dental chart (FDI teeth, surfaces) |
| `/api/v1/treatment-plans/` (+ `present/`, `accept/`, `cancel/`) | Treatment plans with priced items |
| `/api/v1/procedures/` (+ `void/`) | Performed procedures (the charges) |
| `/api/v1/payments/` (+ `void/`) | Payments entered by staff |
| `/api/v1/balances/` (`?has_debt=true`) | Charged, paid and debt per patient |
| `/api/v1/audit-logs/` | Audit trail (owners) |
