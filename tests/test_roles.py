"""The role matrix the clinic owner signed off on, end to end.

Doctor: own patients (add, edit, never delete), own treatments, own appointments,
own statistics. Admin (front desk): every patient, appointment and treatment of the
branch, and books or registers for any doctor. Owner: everything. Patients have no
login at all; they will reach their data through the Telegram bot only.
"""

from datetime import timedelta

from django.utils import timezone

from apps.patients.models import Patient
from apps.tenancy.models import Membership

from .conftest import ids
from .test_finance import procedure

PATIENTS = "/api/v1/patients/"
PROCEDURES = "/api/v1/procedures/"
APPOINTMENTS = "/api/v1/appointments/"


def new_patient(client, **fields):
    body = {"full_name": "New Patient", "phone_number": "+998901112233", **fields}
    return client.post(PATIENTS, body, format="json")


def booking(world, doctor, *, hours=1):
    start = timezone.now() + timedelta(days=1, hours=hours)
    return {
        "patient": str(world.patient_a.pk),
        "doctor": str(doctor.pk),
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(minutes=30)).isoformat(),
    }


def test_patients_have_no_login_role():
    assert {choice for choice, _ in Membership.Role.choices} == {"owner", "admin", "doctor"}


# --- Doctor ------------------------------------------------------------------------


def test_doctor_adds_a_patient_who_stays_on_their_list(world):
    doctor = world.client(world.doctor_a)
    response = new_patient(doctor)
    assert response.status_code == 201, response.json()
    assert response.json()["primary_doctor"] == str(world.doctor_a.pk)
    assert response.json()["id"] in ids(doctor.get(PATIENTS))


def test_doctor_cannot_register_or_move_a_patient_to_a_colleague(world):
    doctor = world.client(world.doctor_a)
    assert new_patient(doctor, primary_doctor=str(world.doctor_a2.pk)).status_code == 403

    url = f"{PATIENTS}{world.patient_a.pk}/"
    assert doctor.patch(url, {"primary_doctor": str(world.doctor_a2.pk)}, format="json").status_code == 403
    world.patient_a.refresh_from_db()
    assert world.patient_a.primary_doctor == world.doctor_a


def test_doctor_edits_but_never_deletes_their_patient(world):
    doctor = world.client(world.doctor_a)
    url = f"{PATIENTS}{world.patient_a.pk}/"
    # The edit form sends the unchanged doctor back; that is not a move.
    response = doctor.patch(url, {"address": "Chilonzor", "primary_doctor": str(world.doctor_a.pk)}, format="json")
    assert response.status_code == 200, response.json()

    # Patients are never deleted, by anyone; there is no DELETE route at all.
    assert doctor.delete(url).status_code in (403, 405)
    assert doctor.post(f"{url}archive/").status_code == 403
    assert Patient.objects.get(pk=world.patient_a.pk).archived_at is None


def test_doctor_sees_only_their_patients(world):
    doctor = world.client(world.doctor_a)
    assert ids(doctor.get(PATIENTS)) == {str(world.patient_a.pk)}
    assert doctor.get(f"{PATIENTS}{world.patient_a2.pk}/").status_code == 404


def test_doctor_treatments_list_is_their_own_work(world):
    mine = procedure(world)
    # A colleague treated the same patient: the patient is shared, the work is not.
    colleagues = procedure(world, doctor=world.doctor_a2, amount="500000")
    doctor = world.client(world.doctor_a)

    assert ids(doctor.get(PROCEDURES)) == {str(mine.pk)}
    assert doctor.patch(f"{PROCEDURES}{colleagues.pk}/", {"notes": "x"}, format="json").status_code == 404
    # The patient's own history stays whole, so the next doctor sees what was done.
    history = ids(doctor.get(f"{PROCEDURES}?patient={world.patient_a.pk}"))
    assert history == {str(mine.pk), str(colleagues.pk)}


def test_doctor_books_only_their_own_appointments(world):
    doctor = world.client(world.doctor_a)
    assert doctor.post(APPOINTMENTS, booking(world, world.doctor_a), format="json").status_code == 201
    assert doctor.post(APPOINTMENTS, booking(world, world.doctor_a2, hours=3), format="json").status_code == 403
    assert {row["doctor"] for row in doctor.get(APPOINTMENTS).json()["results"]} == {str(world.doctor_a.pk)}


def test_doctor_has_no_management(world):
    doctor = world.client(world.doctor_a)
    assert doctor.post("/api/v1/staff/", {}, format="json").status_code == 403
    assert doctor.get("/api/v1/payroll/?month=2026-10").status_code == 403
    assert doctor.get("/api/v1/reports/finance/?from=2026-10-01&to=2026-10-31").status_code == 403


# --- Admin -------------------------------------------------------------------------


def test_admin_sees_every_patient_treatment_and_appointment(world):
    procedure(world)
    procedure(world, doctor=world.doctor_a2, patient=world.patient_a2, amount="500000")
    admin = world.client(world.admin_a)
    admin.post(APPOINTMENTS, booking(world, world.doctor_a2), format="json")

    assert ids(admin.get(PATIENTS)) == {str(world.patient_a.pk), str(world.patient_a2.pk)}
    assert len(admin.get(PROCEDURES).json()["results"]) == 2
    assert {row["doctor"] for row in admin.get(APPOINTMENTS).json()["results"]} == {str(world.doctor_a2.pk)}


def test_admin_registers_and_books_for_any_doctor(world):
    admin = world.client(world.admin_a)
    response = new_patient(admin, primary_doctor=str(world.doctor_a2.pk))
    assert response.status_code == 201
    assert response.json()["primary_doctor"] == str(world.doctor_a2.pk)
    for doctor in (world.doctor_a, world.doctor_a2):
        assert admin.post(APPOINTMENTS, booking(world, doctor), format="json").status_code == 201


def test_admin_has_no_management_or_statistics(world):
    admin = world.client(world.admin_a)
    assert admin.post("/api/v1/staff/", {}, format="json").status_code == 403
    assert admin.get("/api/v1/reports/statistics/?from=2026-10-01&to=2026-10-31").status_code == 403
    assert admin.get("/api/v1/payroll/?month=2026-10").status_code == 403


# --- Owner -------------------------------------------------------------------------


def test_owner_can_do_everything_the_others_can(world):
    from apps.tenancy.permissions import ROLE_PERMISSIONS

    owner = ROLE_PERMISSIONS[Membership.Role.OWNER]
    assert ROLE_PERMISSIONS[Membership.Role.ADMIN] <= owner
    # `payroll:view_own` is a doctor's own month; the owner reads everyone's via `payroll:view`.
    assert ROLE_PERMISSIONS[Membership.Role.DOCTOR] - {"payroll:view_own"} <= owner
    assert "payroll:view" in owner

    client = world.client(world.owner, clinic=world.branch_a)
    assert new_patient(client, primary_doctor=str(world.doctor_a.pk)).status_code == 201
    assert client.post(f"{PATIENTS}{world.patient_a.pk}/archive/").status_code == 200
