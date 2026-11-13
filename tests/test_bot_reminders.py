"""Patient appointment reminders: who gets one, when, and never twice."""

from datetime import datetime, timedelta

from apps.bot import content, dialog
from apps.bot.models import AppointmentReminder
from apps.scheduling.models import Appointment


def link(patient, chat_id=5001):
    account = patient.bot_account
    account.telegram_chat_id = chat_id
    account.save(update_fields=["telegram_chat_id"])
    return account


def visit(world, patient, start, status=Appointment.Status.SCHEDULED, booked_ahead=timedelta(days=3)):
    item = Appointment.objects.create(
        clinic=world.branch_a,
        patient=patient,
        doctor=world.doctor_a,
        start_at=start,
        end_at=start + timedelta(minutes=30),
        status=status,
    )
    # created_at is auto_now_add; move it to model a booking made earlier.
    Appointment.objects.filter(pk=item.pk).update(created_at=start - booked_ahead)
    return item


def local(world, day_offset, hour):
    zone = content.zone_of(world.branch_a)
    day = datetime.now(zone).date() + timedelta(days=day_offset)
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=zone)


def test_day_before_reminder_goes_out_in_the_evening_once(world):
    link(world.patient_a)
    visit(world, world.patient_a, local(world, 1, 10))
    assert dialog.appointment_reminders(local(world, 0, 12)) == []
    sent = dialog.appointment_reminders(local(world, 0, 18))
    assert [chat for chat, _ in sent] == [5001]
    assert "ertaga soat 10:00" in sent[0][1]
    assert dialog.appointment_reminders(local(world, 0, 18) + timedelta(minutes=10)) == []


def test_two_hour_reminder_says_today(world):
    link(world.patient_a)
    start = local(world, 0, 14)
    visit(world, world.patient_a, start)
    sent = dialog.appointment_reminders(start - timedelta(hours=2))
    assert len(sent) == 1 and "bugun soat 14:00" in sent[0][1]
    assert dialog.appointment_reminders(start - timedelta(hours=1, minutes=50)) == []


def test_visit_booked_inside_the_two_hour_window_gets_no_reminder(world):
    link(world.patient_a)
    start = local(world, 0, 14)
    visit(world, world.patient_a, start, booked_ahead=timedelta(minutes=45))
    assert dialog.appointment_reminders(start - timedelta(hours=1)) == []


def test_a_moved_visit_is_reminded_again(world):
    link(world.patient_a)
    item = visit(world, world.patient_a, local(world, 1, 10))
    dialog.appointment_reminders(local(world, 0, 18))
    item.start_at, item.end_at = local(world, 1, 11), local(world, 1, 11) + timedelta(minutes=30)
    item.save()
    assert len(dialog.appointment_reminders(local(world, 0, 19))) == 1
    assert AppointmentReminder.objects.count() == 2


def test_only_linked_active_patients_with_open_visits_are_reminded(world):
    start = local(world, 1, 10)
    visit(world, world.patient_a, start)  # never linked the bot
    link(world.patient_a2, 5002)
    visit(world, world.patient_a2, start, Appointment.Status.CANCELLED)
    assert dialog.appointment_reminders(local(world, 0, 18)) == []
    gone = world.patient_a
    link(gone, 5003)
    gone.archived_at = datetime.now(content.zone_of(world.branch_a))
    gone.save(update_fields=["archived_at"])
    assert dialog.appointment_reminders(local(world, 0, 18)) == []


def test_a_lead_is_reminded_like_a_patient(world):
    # Leads are patients without registered_at (backend PR "leads"); the query must not depend on it.
    link(world.patient_a)
    visit(world, world.patient_a, local(world, 1, 9))
    assert len(dialog.appointment_reminders(local(world, 0, 20))) == 1


def test_reminders_carry_only_the_patients_own_visit(world):
    link(world.patient_a, 5001)
    link(world.patient_a2, 5002)
    visit(world, world.patient_a, local(world, 1, 10))
    sent = dialog.appointment_reminders(local(world, 0, 18))
    assert [chat for chat, _ in sent] == [5001]
