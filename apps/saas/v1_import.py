"""One-off import of one clinic from the SalomatOS v1 database into a new v2 organization.

v1 kept everyone (owner, doctors, patients) in `authentication_user` and pointed
every row's `clinic_id` at the owner's user row, not at `clinic_clinic`. v1 had
no payments table: a treatment carried `total_paid`, so each paid treatment
becomes one cash payment dated like the treatment.

The source is read through its own read-only connection; nothing is written to
v1. Every write happens in one transaction, so a failed run leaves v2 untouched.
Reports hold counts only, never names or phone numbers.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg2
from django.db import transaction
from django.utils import timezone
from psycopg2.extras import RealDictCursor

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.billing.models import Payment
from apps.catalog.models import Service
from apps.clinical.models import Prescription, PrescriptionItem
from apps.core.validators import FDI_TEETH, PHONE_RE
from apps.dental.models import Procedure
from apps.patients.models import Patient
from apps.saas import credentials, passwords
from apps.saas.models import Contract
from apps.scheduling.models import Appointment
from apps.tenancy.models import Clinic, Membership, Organization, Specialty
from apps.tenancy.specialties import ensure_dental_specialty, looks_dental

# v1 stored a booking time only; every slot was half an hour.
APPOINTMENT_LENGTH = timedelta(minutes=30)
# A treatment has a date and no time; midday keeps it on the same day in any report.
DEFAULT_TIME = time(12, 0)
PAYMENT_NOTE = "v1"
# Stand-ins for rows whose patient or service was deleted in v1 (the link became NULL).
DELETED_PATIENT_NAME = "O'chirilgan bemor (v1)"
DELETED_SERVICE_NAME = "O'chirilgan xizmat (v1)"
SMALLINT_MAX = 32767


class V1ImportError(Exception):
    """A problem that stops the import before anything is written."""


class _DryRun(Exception):
    pass


@dataclass
class Report:
    counts: Counter = field(default_factory=Counter)
    issues: Counter = field(default_factory=Counter)
    totals: dict = field(default_factory=dict)
    organization_id: str | None = None
    owner_username: str | None = None
    committed: bool = False


def normalize_phone(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 9:
        digits = "998" + digits
    candidate = "+" + digits if digits else ""
    return candidate if PHONE_RE.match(candidate) else ""


def _tooth(value) -> int | None:
    return value if value in FDI_TEETH else None


def _meal(value: str) -> str:
    text = (value or "").lower()
    if any(word in text for word in ("before", "oldin", "avval", "до")):
        return PrescriptionItem.MealRelation.BEFORE
    if any(word in text for word in ("after", "keyin", "кейин", "после")):
        return PrescriptionItem.MealRelation.AFTER
    if any(word in text for word in ("with", "vaqtida", "во время")):
        return PrescriptionItem.MealRelation.WITH
    return PrescriptionItem.MealRelation.ANY


def _times_per_day(value: str) -> int:
    match = re.search(r"\d+", value or "")
    return max(1, min(int(match.group()), 24)) if match else 1


def _small(value) -> int:
    return max(0, min(int(value or 0), SMALLINT_MAX))


class _Source:
    def __init__(self, conninfo: str, clinic_id: int):
        self.conn = psycopg2.connect(conninfo, cursor_factory=RealDictCursor)
        self.conn.set_session(readonly=True)
        self.clinic_id = clinic_id

    def close(self):
        self.conn.rollback()
        self.conn.close()

    def rows(self, sql: str, params=None) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params or {})
            return cur.fetchall()

    def load(self) -> dict:
        clinic = self.rows(
            "select id, name, phone_number, address, working_hours, admin_id from clinic_clinic where id = %(id)s",
            {"id": self.clinic_id},
        )
        if not clinic:
            raise V1ImportError(f"v1 clinic {self.clinic_id} not found.")
        clinic = clinic[0]
        if clinic["admin_id"] is None:
            raise V1ImportError(f"v1 clinic {self.clinic_id} has no owner.")
        tenant = {"tenant": clinic["admin_id"]}
        users = self.rows(
            "select id, username, full_name, phone_number, birth_date, address, role, is_active, doctor_id,"
            " doctor_type_id, experience, biography, created_at"
            " from authentication_user where clinic_id = %(tenant)s or id = %(tenant)s",
            tenant,
        )
        patient_ids = [u["id"] for u in users if u["role"] == "patient" and u["id"] != clinic["admin_id"]]
        scope = {**tenant, "patients": patient_ids}
        # A row counts as this clinic's when either its clinic or its patient is.
        owned = "(clinic_id = %(tenant)s or patient_id = any(%(patients)s))"
        return {
            "clinic": clinic,
            "users": users,
            "doctor_types": self.rows(
                "select id, name from authentication_doctortype where clinic_id = %(tenant)s order by id", tenant
            ),
            "treatment_types": self.rows(
                "select id, name, price, doctor_type_id from clinic_treatmenttype where clinic_id = %(tenant)s"
                " order by id",
                tenant,
            ),
            "treatments": self.rows(
                "select id, created_at, total_treatment_cost, total_paid, tooth_number, start_date, notes,"
                f" doctor_id, patient_id, treatment_type_id, status from clinic_treatment where {owned} order by id",
                scope,
            ),
            "appointments": self.rows(
                'select id, created_at, date, "time", notes, status, doctor_id, patient_id, tooth_number,'
                f" treatment_type from calendars_appointment where {owned} order by id",
                scope,
            ),
            "recipes": self.rows(
                f"select id, created_at, notes, doctor_id, patient_id from core_recipe where {owned} order by id",
                scope,
            ),
            "medicines": self.rows(
                "select m.recipe_id, m.name, m.dose, m.type, m.frequency, m.duration, m.meal, m.minutes"
                " from core_medicine m join core_recipe r on r.id = m.recipe_id"
                " where (r.clinic_id = %(tenant)s or r.patient_id = any(%(patients)s)) order by m.id",
                scope,
            ),
            "gallery": self.rows(
                "select count(*) as n from authentication_gallery where clinic_id = %(tenant)s", tenant
            )[0]["n"],
        }


class Importer:
    def __init__(self, data: dict, *, name: str | None, username_prefix: str):
        self.data = data
        self.name = name or data["clinic"]["name"]
        self.prefix = username_prefix
        self.report = Report()
        self.audit: list[AuditLog] = []
        self._placeholder_patient: Patient | None = None
        self._placeholder_service: Service | None = None

    # -- entry point ---------------------------------------------------------

    def run(self, commit: bool) -> Report:
        self._preflight()
        try:
            with transaction.atomic():
                self._import()
                AuditLog.objects.bulk_create(self.audit)
                if not commit:
                    raise _DryRun
        except _DryRun:
            pass
        self.report.committed = commit
        return self.report

    def _preflight(self):
        if Organization.objects.filter(name=self.name).exists():
            raise V1ImportError("An organization with this name already exists; pass another --name.")
        taken = User.objects.filter(username__in=[self._username(u) for u in self._staff()]).values_list(
            "username", flat=True
        )
        if taken:
            raise V1ImportError(f"Usernames already taken in v2: {', '.join(sorted(taken))}. Use --username-prefix.")

    def _staff(self) -> list[dict]:
        owner_id = self.data["clinic"]["admin_id"]
        return [u for u in self.data["users"] if u["id"] == owner_id or u["role"] in ("doctor", "admin")]

    def _username(self, user: dict) -> str:
        return f"{self.prefix}{user['username'] or f'v1_{user["id"]}'}"

    # -- the import ----------------------------------------------------------

    def _import(self):
        source = self.data["clinic"]
        self.tz = ZoneInfo("Asia/Tashkent")
        organization = Organization.objects.create(name=self.name)
        Contract.objects.create(organization=organization)
        owner_row = next((u for u in self.data["users"] if u["id"] == source["admin_id"]), None)
        if owner_row is None:
            raise V1ImportError("The v1 owner row is missing.")
        password = passwords.generate()
        owner = User.objects.create_user(
            username=self._username(owner_row),
            password=password,
            full_name=owner_row["full_name"] or self.name,
            phone_number=normalize_phone(owner_row["phone_number"]),
        )
        # Shown once in the platform panel ("Login va parollar") until the owner gets a new one.
        credentials.issue(owner, password)
        organization.owners.add(owner)
        self.clinic = Clinic.objects.create(
            organization=organization,
            name=self.name,
            phone_number=normalize_phone(source["phone_number"]),
            address=source["address"] or "",
            working_hours=source["working_hours"] or {},
        )
        # The post_save signal on Clinic made the owner a member.
        self.owner = Membership.objects.get(user=owner, clinic=self.clinic)
        self.report.organization_id = str(organization.pk)
        self.report.owner_username = owner.username
        self.report.counts["owner"] = 1

        self._specialties()
        self._staff_members(source["admin_id"])
        self._services()
        self._patients()
        self._procedures()
        self._appointments()
        self._prescriptions()
        self.report.issues["gallery_files_not_imported"] = self.data["gallery"]
        self.report.issues["other_superadmins_skipped"] = sum(
            1 for u in self.data["users"] if u["role"] == "superadmin" and u["id"] != source["admin_id"]
        )

    def _specialties(self):
        self.specialties = {}
        by_name = {}
        for row in self.data["doctor_types"]:
            key = row["name"].strip()
            if key not in by_name:
                # v1 dentists join the clinic's built-in dental specialty, not a second one.
                by_name[key] = (
                    ensure_dental_specialty(self.clinic)
                    if looks_dental(key)
                    else Specialty.objects.create(clinic=self.clinic, name=key)
                )
            self.specialties[row["id"]] = by_name[key]
        self.report.counts["specialties"] = len(by_name)

    def _staff_members(self, owner_id: int):
        self.doctors = {owner_id: self.owner}
        for row in self._staff():
            if row["id"] == owner_id:
                continue
            # No password: the owner sets each one in Boshqaruv before staff sign in.
            user = User.objects.create_user(
                username=self._username(row),
                password=None,
                full_name=row["full_name"],
                phone_number=normalize_phone(row["phone_number"]),
                is_active=row["is_active"],
            )
            role = Membership.Role.DOCTOR if row["role"] == "doctor" else Membership.Role.ADMIN
            membership = Membership.objects.create(
                user=user,
                clinic=self.clinic,
                role=role,
                is_active=row["is_active"],
                specialty=self.specialties.get(row["doctor_type_id"]),
                experience_years=_small(row["experience"]) if row["experience"] is not None else None,
                biography=row["biography"] or "",
            )
            self.doctors[row["id"]] = membership
            self.report.counts[f"staff_{role}"] += 1

    def _services(self):
        self.services = {}
        self.services_by_name = {}
        for row in self.data["treatment_types"]:
            service = Service.objects.create(
                clinic=self.clinic,
                name=row["name"],
                price=Decimal(row["price"] or 0),
                specialty=self.specialties.get(row["doctor_type_id"]),
            )
            self.services[row["id"]] = service
            self.services_by_name.setdefault(row["name"].strip().lower(), service)
        self.report.counts["services"] = len(self.services)

    def _patients(self):
        self.patients = {}
        for row in self.data["users"]:
            if row["role"] != "patient" or row["id"] == self.data["clinic"]["admin_id"]:
                continue
            phone = normalize_phone(row["phone_number"])
            if not phone:
                self.report.issues["patient_phone_invalid"] += 1
            patient = Patient.objects.create(
                clinic=self.clinic,
                full_name=row["full_name"],
                phone_number=phone,
                birth_date=row["birth_date"],
                address=row["address"] or "",
                primary_doctor=self.doctors.get(row["doctor_id"]) if row["doctor_id"] in self.doctors else None,
                registered_at=row["created_at"] or timezone.now(),
            )
            self._keep_created_at(Patient, patient, row["created_at"])
            self.patients[row["id"]] = patient
            self._audit(patient)
        self.report.counts["patients"] = len(self.patients)

    def _doctor(self, v1_id, kind: str) -> Membership:
        doctor = self.doctors.get(v1_id)
        if doctor is None:
            # The work stays on record under the owner instead of being dropped.
            self.report.issues[f"{kind}_doctor_unknown_assigned_to_owner"] += 1
            return self.owner
        return doctor

    def _local(self, day, at: time = DEFAULT_TIME) -> datetime:
        return datetime.combine(day, at, tzinfo=self.tz)

    def _procedures(self):
        source_cost = source_paid = Decimal(0)
        cost = paid = Decimal(0)
        for row in self.data["treatments"]:
            source_cost += row["total_treatment_cost"]
            source_paid += row["total_paid"]
            patient = self.patients.get(row["patient_id"])
            service = self.services.get(row["treatment_type_id"])
            if patient is None and row["patient_id"] is None:
                # v1 nulled the link when a patient was deleted; the money still belongs in the books.
                patient = self._deleted_patient()
                self.report.issues["treatment_patient_deleted_kept_on_placeholder"] += 1
            if patient is None:
                self.report.issues["treatment_patient_elsewhere_skipped"] += 1
                continue
            if service is None:
                service = self._deleted_service()
                self.report.issues["treatment_service_deleted_kept_on_placeholder"] += 1
            if row["tooth_number"] is not None and _tooth(row["tooth_number"]) is None:
                self.report.issues["treatment_tooth_not_fdi_left_empty"] += 1
            doctor = self._doctor(row["doctor_id"], "treatment")
            performed_at = self._local(row["start_date"])
            completed = row["status"] == "completed"
            procedure = Procedure.objects.create(
                clinic=self.clinic,
                patient=patient,
                doctor=doctor,
                service=service,
                unit_price=Decimal(row["total_treatment_cost"]),
                tooth=_tooth(row["tooth_number"]),
                performed_at=performed_at,
                status=Procedure.Status.COMPLETED if completed else Procedure.Status.IN_PROGRESS,
                completed_at=performed_at if completed else None,
                completed_by=doctor if completed else None,
                notes=row["notes"] or "",
            )
            self._keep_created_at(Procedure, procedure, row["created_at"])
            self._audit(procedure)
            self.report.counts["procedures"] += 1
            cost += procedure.unit_price
            if row["total_paid"] > 0:
                if row["total_paid"] > row["total_treatment_cost"]:
                    self.report.issues["treatment_overpaid"] += 1
                payment = Payment.objects.create(
                    clinic=self.clinic,
                    patient=patient,
                    amount=Decimal(row["total_paid"]),
                    method=Payment.Method.CASH,
                    # v1 kept no payment date; the user chose the treatment's date.
                    paid_at=performed_at,
                    received_by=self.owner,
                    notes=PAYMENT_NOTE,
                )
                self._audit(payment)
                self.report.counts["payments"] += 1
                paid += payment.amount
        self.report.totals = {
            "v1_cost": source_cost,
            "v1_paid": source_paid,
            "v1_debt": source_cost - source_paid,
            "v2_cost": cost,
            "v2_paid": paid,
            "v2_debt": cost - paid,
        }

    def _appointments(self):
        now = timezone.now()
        for row in self.data["appointments"]:
            patient = self.patients.get(row["patient_id"])
            if patient is None:
                self.report.issues["appointment_without_patient_skipped"] += 1
                continue
            start = self._local(row["date"], row["time"])
            end = start + APPOINTMENT_LENGTH
            if end <= now or row["status"] == "completed":
                status = Appointment.Status.COMPLETED
            else:
                status = Appointment.Status.SCHEDULED
            kind = (row["treatment_type"] or "").strip()
            service = self.services_by_name.get(kind.lower()) if kind else None
            notes = [row["notes"] or ""]
            if kind and service is None:
                notes.insert(0, kind)
            if row["tooth_number"]:
                notes.insert(0, f"Tish: {row['tooth_number']}")
            appointment = Appointment.objects.create(
                clinic=self.clinic,
                patient=patient,
                doctor=self._doctor(row["doctor_id"], "appointment"),
                service=service,
                start_at=start,
                end_at=end,
                status=status,
                notes="\n".join(part for part in notes if part),
            )
            self._keep_created_at(Appointment, appointment, row["created_at"])
            self._audit(appointment)
            self.report.counts[f"appointments_{status}"] += 1

    def _prescriptions(self):
        items = {}
        for row in self.data["medicines"]:
            items.setdefault(row["recipe_id"], []).append(row)
        for row in self.data["recipes"]:
            patient = self.patients.get(row["patient_id"])
            if patient is None:
                self.report.issues["prescription_without_patient_skipped"] += 1
                continue
            prescription = Prescription.objects.create(
                clinic=self.clinic,
                patient=patient,
                doctor=self._doctor(row["doctor_id"], "prescription"),
                notes=row["notes"] or "",
            )
            self._keep_created_at(Prescription, prescription, row["created_at"])
            self._audit(prescription)
            for item in items.get(row["id"], []):
                instructions = item["frequency"] or ""
                if item["minutes"]:
                    instructions = f"{instructions}, {item['minutes']} min".strip(", ")
                PrescriptionItem.objects.create(
                    prescription=prescription,
                    medicine=item["name"][:255],
                    dose=str(item["dose"]),
                    form=(item["type"] or "")[:64],
                    times_per_day=_times_per_day(item["frequency"]),
                    duration_days=_small(item["duration"]),
                    meal_relation=_meal(item["meal"]),
                    instructions=instructions[:255],
                )
            self.report.counts["prescriptions"] += 1

    # -- helpers -------------------------------------------------------------

    def _deleted_patient(self) -> Patient:
        if self._placeholder_patient is None:
            # Archived, so it stays out of every patient list and search.
            self._placeholder_patient = Patient.objects.create(
                clinic=self.clinic, full_name=DELETED_PATIENT_NAME, phone_number="", archived_at=timezone.now()
            )
            self._audit(self._placeholder_patient)
        return self._placeholder_patient

    def _deleted_service(self) -> Service:
        if self._placeholder_service is None:
            # Inactive, so nobody can pick it for new work.
            self._placeholder_service = Service.objects.create(
                clinic=self.clinic, name=DELETED_SERVICE_NAME, price=Decimal(0), is_active=False
            )
        return self._placeholder_service

    @staticmethod
    def _keep_created_at(model, obj, created_at):
        # auto_now_add ignores a passed value, so the v1 timestamp is written afterwards.
        if created_at is not None:
            model.objects.filter(pk=obj.pk).update(created_at=created_at)

    def _audit(self, obj):
        self.audit.append(
            AuditLog(
                clinic=self.clinic,
                actor=None,
                action=AuditLog.Action.CREATE,
                target_type=obj._meta.label_lower,
                target_id=obj.pk,
            )
        )


def import_clinic(conninfo: str, clinic_id: int, *, name=None, username_prefix="", commit=False) -> Report:
    source = _Source(conninfo, clinic_id)
    try:
        data = source.load()
    finally:
        source.close()
    return Importer(data, name=name, username_prefix=username_prefix).run(commit)
