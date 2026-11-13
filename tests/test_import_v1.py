from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from django.utils import timezone
from psycopg2.extensions import make_dsn

from apps.accounts.models import User
from apps.billing.models import Payment
from apps.clinical.models import Prescription
from apps.dental.models import Procedure
from apps.patients.models import Patient
from apps.saas import credentials
from apps.scheduling.models import Appointment
from apps.tenancy.models import Membership, Organization

# Only the v1 columns the importer reads; foreign keys are left out on purpose so
# rows can point at missing users, as they can in a real v1 database.
V1_SCHEMA = """
create schema v1src;
set search_path = v1src;
create table authentication_user (id bigint primary key, username varchar(255), full_name varchar(255) not null,
  phone_number varchar(14) not null, birth_date date, address varchar(255), role varchar(200) not null,
  is_active boolean not null, doctor_id bigint, doctor_type_id bigint, experience integer, biography text,
  created_at timestamptz, clinic_id bigint);
create table clinic_clinic (id bigint primary key, name varchar(255) not null, phone_number varchar(14) not null,
  address varchar(255) not null, working_hours jsonb, admin_id bigint);
create table authentication_doctortype (id bigint primary key, name varchar(255) not null, clinic_id bigint);
create table clinic_treatmenttype (id bigint primary key, name varchar(255) not null, price integer,
  clinic_id bigint, doctor_type_id bigint);
create table clinic_treatment (id bigint primary key, created_at timestamptz, total_treatment_cost integer not null,
  total_paid integer not null, tooth_number integer, start_date date not null, notes text, doctor_id bigint,
  patient_id bigint, treatment_type_id bigint, status varchar(20) not null, clinic_id bigint);
create table calendars_appointment (id bigint primary key, created_at timestamptz, date date not null,
  "time" time not null, notes text, status varchar(20) not null, doctor_id bigint not null, patient_id bigint,
  clinic_id bigint, tooth_number integer, treatment_type varchar(255));
create table core_recipe (id bigint primary key, created_at timestamptz, notes text, doctor_id bigint,
  patient_id bigint, clinic_id bigint);
create table core_medicine (id bigint primary key, name varchar(255) not null, dose integer not null,
  type varchar(255) not null, frequency varchar(255) not null, duration integer not null,
  meal varchar(255) not null, minutes integer not null, recipe_id bigint not null);
create table authentication_gallery (id bigint primary key, clinic_id bigint);
"""

PAST = date(2026, 3, 10)
FUTURE = timezone.localdate() + timedelta(days=30)


def _seed(cur):
    cur.execute(V1_SCHEMA)
    users = [
        # id, username, name, phone, role, doctor_id, doctor_type, clinic_id
        (10, "alixmed", "Owner", "+998901110000", "superadmin", None, None, None),
        (11, "dr_one", "Doctor One", "+998901110001", "doctor", None, 1, 10),
        (12, "reception", "Admin One", "+998901110002", "admin", None, None, 10),
        (13, None, "Patient One", "+998901110003", "patient", 11, None, 10),
        (14, None, "Patient Two", "90 111 00 04", "patient", None, None, 10),
        (20, "dentaflow", "Other Owner", "+998901110020", "superadmin", None, None, None),
        (30, None, "Other Patient", "+998901110030", "patient", None, None, 20),
    ]
    for uid, username, name, phone, role, doctor_id, doctor_type, clinic_id in users:
        cur.execute(
            "insert into authentication_user (id, username, full_name, phone_number, role, is_active, doctor_id,"
            " doctor_type_id, experience, created_at, clinic_id) values (%s,%s,%s,%s,%s,true,%s,%s,5,now(),%s)",
            (uid, username, name, phone, role, doctor_id, doctor_type, clinic_id),
        )
    cur.execute(
        "insert into clinic_clinic values (2, 'ALI X MED', '+998901110000', 'Addr', null, 10),"
        " (1, 'Denta Flow', '+998901110020', 'Addr', null, 20)"
    )
    cur.execute("insert into authentication_doctortype values (1, 'Terapevt', 10)")
    cur.execute(
        "insert into clinic_treatmenttype values (1, 'Plomba', 300000, 10, 1), (2, 'Konsultatsiya', null, 10, null),"
        " (3, 'Other clinic service', 1, 20, null)"
    )
    cur.execute(
        "insert into clinic_treatment values"
        " (1, now(), 500000, 200000, 36, %(past)s, 'n', 11, 13, 1, 'completed', 10),"
        " (2, now(), 100000, 0, 99, %(past)s, null, 11, 14, 2, 'in_progress', 10),"
        " (3, now(), 50000, 50000, null, %(past)s, null, 999, 13, 2, 'in_progress', 10),"
        " (4, now(), 70000, 70000, null, %(past)s, null, 20, 30, 3, 'completed', 20),"
        # v1 nulls the link when a patient or a service is deleted.
        " (5, now(), 30000, 30000, null, %(past)s, null, 11, null, 1, 'completed', 10),"
        " (6, now(), 20000, 10000, null, %(past)s, null, 11, 13, null, 'completed', 10)",
        {"past": PAST},
    )
    cur.execute(
        "insert into calendars_appointment values"
        " (1, now(), %(past)s, '10:00', null, 'in_progress', 11, 13, 10, 36, 'Plomba'),"
        " (2, now(), %(future)s, '11:00', 'note', 'in_progress', 11, 14, 10, null, 'Unknown kind'),"
        " (3, now(), %(future)s, '11:00', null, 'in_progress', 20, 30, 20, null, null)",
        {"past": PAST, "future": FUTURE},
    )
    cur.execute("insert into core_recipe values (1, now(), null, 11, 13, 10)")
    cur.execute("insert into core_medicine values (1, 'Ibuprofen', 400, 'tablet', '3 marta', 5, 'keyin', 0, 1)")
    cur.execute("insert into authentication_gallery values (1, 10), (2, 20)")
    # The seeding cursor shares Django's connection, which must go back to the v2 tables.
    cur.execute("reset search_path")


@pytest.fixture
def v1_source(transactional_db):
    with connection.cursor() as cur:
        _seed(cur)
    settings = connection.settings_dict
    conninfo = make_dsn(
        dbname=settings["NAME"],
        user=settings["USER"],
        password=settings["PASSWORD"],
        host=settings["HOST"],
        port=settings["PORT"],
        options="-c search_path=v1src",
    )
    yield conninfo
    with connection.cursor() as cur:
        cur.execute("drop schema v1src cascade")


def _run(conninfo, *extra) -> str:
    out = StringIO()
    call_command("import_v1", "--source", conninfo, "--clinic", "2", *extra, stdout=out)
    return out.getvalue()


def test_dry_run_saves_nothing(v1_source):
    output = _run(v1_source)
    assert "Dry run" in output
    assert "patients: 2" in output
    assert not Organization.objects.exists()
    assert not Patient.objects.exists()
    assert not User.objects.exists()


def test_output_has_no_patient_data(v1_source):
    output = _run(v1_source, "--commit")
    for value in ("Patient One", "Patient Two", "+998901110003", "Ibuprofen"):
        assert value not in output


def test_commit_imports_only_the_chosen_clinic(v1_source):
    _run(v1_source, "--commit", "--name", "ALI X MED (test)")

    org = Organization.objects.get()
    assert org.name == "ALI X MED (test)"
    clinic = org.clinics.get()
    assert Patient.objects.filter(clinic=clinic, archived_at__isnull=True).count() == 2
    assert Patient.objects.count() == 3
    assert not User.objects.filter(username="dentaflow").exists()

    owner = User.objects.get(username="alixmed")
    assert org.owners.filter(pk=owner.pk).exists()
    assert credentials.current(owner)
    doctor = Membership.objects.get(user__username="dr_one")
    assert doctor.role == Membership.Role.DOCTOR
    assert doctor.specialty.name == "Terapevt"
    assert not doctor.user.has_usable_password()
    assert Membership.objects.get(user__username="reception").role == Membership.Role.ADMIN


def test_money_matches_v1(v1_source):
    output = _run(v1_source, "--commit")
    assert Procedure.objects.count() == 5
    assert sum(p.unit_price for p in Procedure.objects.all()) == Decimal("700000")
    payments = Payment.objects.all()
    assert sum(p.amount for p in payments) == Decimal("290000")
    assert {timezone.localtime(p.paid_at).date() for p in payments} == {PAST}
    assert "v1_debt: 410000" in output
    assert "v2_debt: 410000\n" in output


def test_mapping_rules(v1_source):
    output = _run(v1_source, "--commit")
    filled = Procedure.objects.get(unit_price=500000)
    assert filled.tooth == 36
    assert filled.status == Procedure.Status.COMPLETED
    assert Procedure.objects.get(unit_price=100000).tooth is None
    # Unknown doctor: kept under the owner, and reported.
    owner = Membership.objects.get(role=Membership.Role.OWNER)
    assert Procedure.objects.get(unit_price=50000).doctor == owner
    assert "treatment_doctor_unknown_assigned_to_owner: 1" in output

    past = Appointment.objects.get(start_at__date=PAST)
    assert past.status == Appointment.Status.COMPLETED
    assert past.end_at - past.start_at == timedelta(minutes=30)
    assert past.service.name == "Plomba"
    future = Appointment.objects.get(status=Appointment.Status.SCHEDULED)
    assert future.service is None
    assert "Unknown kind" in future.notes

    assert Patient.objects.get(full_name="Patient Two").phone_number == "+998901110004"
    item = Prescription.objects.get().items.get()
    assert item.times_per_day == 3
    assert item.meal_relation == "after"
    assert "gallery_files_not_imported: 1" in output


def test_second_run_with_the_same_name_is_refused(v1_source):
    _run(v1_source, "--commit")
    with pytest.raises(CommandError):
        _run(v1_source, "--commit")
    assert Organization.objects.count() == 1


def test_existing_username_needs_a_prefix(v1_source):
    User.objects.create_user(username="dr_one", password="x", full_name="Someone")
    with pytest.raises(CommandError):
        _run(v1_source, "--commit")
    _run(v1_source, "--commit", "--username-prefix", "t_")
    assert User.objects.filter(username="t_dr_one").exists()


def test_rows_whose_patient_or_service_was_deleted_are_kept(v1_source):
    output = _run(v1_source, "--commit")
    orphan = Procedure.objects.get(unit_price=30000)
    assert orphan.patient.archived_at is not None
    assert orphan.patient.full_name == "O'chirilgan bemor (v1)"
    assert orphan.patient.payments.get().amount == Decimal("30000")
    no_service = Procedure.objects.get(unit_price=20000)
    assert no_service.patient.full_name == "Patient One"
    assert no_service.service.name == "O'chirilgan xizmat (v1)"
    assert not no_service.service.is_active
    assert "treatment_patient_deleted_kept_on_placeholder: 1" in output
    assert "treatment_service_deleted_kept_on_placeholder: 1" in output
