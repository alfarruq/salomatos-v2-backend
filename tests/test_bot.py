from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.audit.models import AuditLog
from apps.billing.models import Payment
from apps.bot import content, dialog, texts
from apps.bot.credentials import MAX_FAILED_ATTEMPTS, LoginResult, authenticate, reveal
from apps.bot.models import BotAccount
from apps.catalog.models import Service
from apps.clinical.models import Prescription, PrescriptionItem
from apps.dental.models import Procedure
from apps.patients.models import Patient
from apps.scheduling.models import Appointment

CHAT = 1001
OTHER_CHAT = 2002


def creds(account):
    return reveal(account)


def sign_in(chat_id, account):
    state = {}
    dialog.handle_start(chat_id, state)
    dialog.handle_text(chat_id, account.login, state)
    return dialog.handle_text(chat_id, creds(account).password, state)


def texts_of(reply):
    return [out.text for out in reply.messages if out.text]


# Issuing


def test_every_patient_doctor_and_owner_gets_a_login(world):
    assert BotAccount.objects.filter(patient=world.patient_a).exists()
    assert BotAccount.objects.filter(user=world.doctor_a.user).exists()
    assert BotAccount.objects.filter(user=world.owner).exists()
    # Admins have nothing to do in the bot, so no login exists to leak.
    assert not BotAccount.objects.filter(user=world.admin_a.user).exists()


def test_logins_are_random_and_passwords_are_not_stored_in_clear(world):
    account = world.patient_a.bot_account
    password = creds(account).password
    assert len(account.login) == 8 and account.login.isdigit()
    assert password and password not in account.password_hash and password not in account.password_encrypted
    assert account.login != world.patient_a2.bot_account.login


# Reading a login back


def test_admin_reads_a_patients_login_and_it_is_audited(world):
    response = world.client(world.admin_a).get(f"/api/v1/patients/{world.patient_a.pk}/bot-access/")
    assert response.status_code == 200
    account = world.patient_a.bot_account
    assert response.json() == {"login": account.login, "password": creds(account).password, "linked": False}
    assert AuditLog.objects.filter(target_id=account.pk, action=AuditLog.Action.VIEW).exists()


def test_doctor_reads_only_own_patients_login(world):
    api = world.client(world.doctor_a)
    assert api.get(f"/api/v1/patients/{world.patient_a.pk}/bot-access/").status_code == 200
    assert api.get(f"/api/v1/patients/{world.patient_a2.pk}/bot-access/").status_code == 404


def test_other_clinic_cannot_read_a_patients_login(world):
    api = world.client(world.other_admin)
    assert api.get(f"/api/v1/patients/{world.patient_a.pk}/bot-access/").status_code == 404


def test_reset_gives_a_new_password_and_signs_the_chat_out(world):
    account = world.patient_a.bot_account
    old = creds(account).password
    sign_in(CHAT, account)
    response = world.client(world.admin_a).post(f"/api/v1/patients/{world.patient_a.pk}/bot-access/reset/")
    assert response.status_code == 200
    assert response.json()["password"] != old
    assert response.json()["linked"] is False
    assert dialog.handle_text(CHAT, texts.BTN_DOCTOR, {}).messages[0].text == texts.ASK_PASSWORD


def test_owner_reads_staff_logins_admin_cannot(world):
    url = f"/api/v1/staff/{world.doctor_a.pk}/bot-access/"
    response = world.client(world.owner, clinic=world.branch_a).get(url)
    assert response.status_code == 200
    assert response.json()["login"] == world.doctor_a.user.bot_account.login
    assert world.client(world.admin_a).get(url).status_code == 403
    # An admin has no login to show.
    admin_url = f"/api/v1/staff/{world.admin_a.pk}/bot-access/"
    assert world.client(world.owner, clinic=world.branch_a).get(admin_url).status_code == 404


def test_staff_read_their_own_login(world):
    response = world.client(world.doctor_a).get("/api/v1/me/bot-access/")
    assert response.status_code == 200
    assert response.json()["login"] == world.doctor_a.user.bot_account.login
    assert world.client(world.admin_a).get("/api/v1/me/bot-access/").status_code == 404


# Signing in


def test_password_message_is_deleted_and_menu_shown(world):
    reply = sign_in(CHAT, world.patient_a.bot_account)
    assert reply.delete_incoming
    assert texts.BTN_PRESCRIPTIONS in reply.keyboard[0]


def test_wrong_passwords_lock_the_login(world):
    account = world.patient_a.bot_account
    for _ in range(MAX_FAILED_ATTEMPTS):
        assert authenticate(CHAT, account.login, "wrong-pass")[0] == LoginResult.INVALID
    # Even the right password waits out the lock.
    assert authenticate(CHAT, account.login, creds(account).password)[0] == LoginResult.LOCKED


def test_signing_in_on_a_new_chat_signs_the_old_one_out(world):
    account = world.patient_a.bot_account
    sign_in(CHAT, account)
    sign_in(OTHER_CHAT, account)
    account.refresh_from_db()
    assert account.telegram_chat_id == OTHER_CHAT
    assert dialog.handle_text(CHAT, texts.BTN_DOCTOR, {}).messages[0].text == texts.ASK_PASSWORD


def test_archived_patient_cannot_use_the_bot(world):
    account = world.patient_a.bot_account
    sign_in(CHAT, account)
    world.patient_a.archived_at = timezone.now()
    world.patient_a.save()
    assert dialog.handle_text(CHAT, texts.BTN_DOCTOR, {}).messages[0].text == texts.ASK_PASSWORD
    assert authenticate(OTHER_CHAT, account.login, creds(account).password)[0] == LoginResult.INVALID


# Patient


def _prescription(world, patient, medicine):
    rx = Prescription.objects.create(clinic=patient.clinic, patient=patient, doctor=world.doctor_a)
    PrescriptionItem.objects.create(prescription=rx, medicine=medicine, dose="500 mg", times_per_day=2, duration_days=5)
    return rx


def test_patient_sees_only_own_prescriptions(world):
    _prescription(world, world.patient_a, "Amoxicillin")
    foreign = _prescription(world, world.patient_a2, "Ibuprofen")
    sign_in(CHAT, world.patient_a.bot_account)
    body = "\n".join(texts_of(dialog.handle_text(CHAT, texts.BTN_PRESCRIPTIONS, {})))
    assert "Amoxicillin" in body and "Ibuprofen" not in body
    # A forged PDF button for someone else's prescription returns nothing.
    assert dialog.handle_callback(CHAT, f"{dialog.RX_PREFIX}{foreign.pk}").messages == []


def test_patient_sees_treatment_history_and_doctor(world):
    service = Service.objects.create(clinic=world.branch_a, name="Filling", price=Decimal("300000"))
    Procedure.objects.create(
        clinic=world.branch_a,
        patient=world.patient_a,
        doctor=world.doctor_a,
        service=service,
        unit_price=Decimal("300000"),
        performed_at=timezone.now(),
    )
    sign_in(CHAT, world.patient_a.bot_account)
    history = texts_of(dialog.handle_text(CHAT, texts.BTN_PROCEDURES, {}))[0]
    assert "Filling" in history and "300 000 so'm" in history
    doctor = texts_of(dialog.handle_text(CHAT, texts.BTN_DOCTOR, {}))[0]
    assert world.doctor_a.user.full_name in doctor


# Doctor and owner


def _visit(world, patient, doctor, start, status=Appointment.Status.SCHEDULED):
    return Appointment.objects.create(
        clinic=doctor.clinic,
        patient=patient,
        doctor=doctor,
        start_at=start,
        end_at=start + timedelta(minutes=30),
        status=status,
    )


def _today_at(world, hour):
    day = content.today_in(world.branch_a)
    return content.start_of(day, content.zone_of(world.branch_a)) + timedelta(hours=hour)


def test_doctor_morning_message_counts_only_own_visits(world):
    _visit(world, world.patient_a, world.doctor_a, _today_at(world, 10))
    _visit(world, world.patient_a, world.doctor_a, _today_at(world, 11))
    _visit(world, world.patient_a, world.doctor_a, _today_at(world, 12), Appointment.Status.CANCELLED)
    _visit(world, world.patient_a2, world.doctor_a2, _today_at(world, 10))
    sign_in(CHAT, world.doctor_a.user.bot_account)
    messages = dict(dialog.morning_messages())
    assert "2 ta uchrashuv" in messages[CHAT]


def test_doctor_today_shows_own_new_patients_and_procedures(world):
    Patient.objects.create(
        clinic=world.branch_a, full_name="New", phone_number="+998900000009", primary_doctor=world.doctor_a
    )
    sign_in(CHAT, world.doctor_a.user.bot_account)
    body = texts_of(dialog.handle_text(CHAT, texts.BTN_TODAY, {}))[0]
    # patient_a was created today too, by the fixture.
    assert "Yangi bemorlar: 2" in body


def test_owner_evening_report_has_money_and_debt(world):
    service = Service.objects.create(clinic=world.branch_a, name="Crown", price=Decimal("1000000"))
    Procedure.objects.create(
        clinic=world.branch_a,
        patient=world.patient_a,
        doctor=world.doctor_a,
        service=service,
        unit_price=Decimal("1000000"),
        performed_at=_today_at(world, 9),
    )
    Payment.objects.create(
        clinic=world.branch_a,
        patient=world.patient_a,
        amount=Decimal("400000"),
        method=Payment.Method.CASH,
        paid_at=_today_at(world, 10),
        received_by=world.admin_a,
    )
    sign_in(CHAT, world.owner.bot_account)
    report = dict(dialog.evening_reports())[CHAT]
    assert "Muolajalar: 1 ta, 1 000 000 so'm" in report
    assert "Bugun to'langan: 400 000 so'm" in report
    assert "Jami qarz (to'lanishi kerak): 600 000 so'm" in report
    assert "Barcha filiallar" in report
    # The other organization's branch never appears.
    assert world.other_clinic.name not in report


def test_doctor_gets_no_owner_report_and_patient_no_staff_menu(world):
    sign_in(CHAT, world.doctor_a.user.bot_account)
    sign_in(OTHER_CHAT, world.patient_a.bot_account)
    assert CHAT not in dict(dialog.evening_reports())
    reply = dialog.handle_text(OTHER_CHAT, texts.BTN_REPORT, {})
    assert texts.BTN_REPORT not in sum(reply.keyboard, [])


def test_login_typed_with_spaces_still_works(world):
    account = world.patient_a.bot_account
    spaced = f"{account.login[:4]} {account.login[4:]}"
    assert authenticate(CHAT, spaced, creds(account).password)[0] == LoginResult.OK


def test_gallery_skips_files_too_big_for_telegram(world):
    from apps.imaging.models import Attachment

    Attachment.objects.create(
        clinic=world.branch_a,
        patient=world.patient_a,
        kind=Attachment.Kind.CBCT,
        file="clinics/x/attachments/big.dcm",
        size_bytes=dialog.FILE_LIMIT + 1,
    )
    sign_in(CHAT, world.patient_a.bot_account)
    reply = dialog.handle_text(CHAT, texts.BTN_GALLERY, {})
    assert reply.messages[0].file is None
    assert texts.FILE_TOO_BIG in reply.messages[0].text
