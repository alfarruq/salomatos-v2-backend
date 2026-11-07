"""Bot messages, in Uzbek: the bot speaks to patients and staff in the clinic's language.

Plain text only (no parse mode), so a patient's name can never break the markup.
"""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from apps.bot.content import BranchDay, DoctorDay

# Buttons
BTN_PRESCRIPTIONS = "Retseptlarim"
BTN_GALLERY = "Rasmlarim"
BTN_PROCEDURES = "Muolajalarim"
BTN_DOCTOR = "Doktorim"
BTN_TODAY = "Bugun"
BTN_REPORT = "Bugungi hisobot"
BTN_LOGOUT = "Chiqish"

WELCOME = "Assalomu alaykum! Klinika bergan loginingizni yuboring."
ASK_PASSWORD = "Endi parolni yuboring."
LOGIN_OK = "Xush kelibsiz! Kerakli bo'limni tanlang."
LOGIN_INVALID = "Login yoki parol noto'g'ri. Loginni qaytadan yuboring."
LOGIN_LOCKED = "Juda ko'p urinish bo'ldi. 15 daqiqadan keyin qayta urinib ko'ring."
LOGGED_OUT = "Siz botdan chiqdingiz. Qayta kirish uchun loginni yuboring."
NEED_LOGIN = "Avval kiring: klinika bergan loginingizni yuboring."
NOTHING = "Hozircha ma'lumot yo'q."
NO_DOCTOR = "Sizga hali doktor biriktirilmagan."
NO_ROLE = "Bu hisob uchun botda bo'lim yo'q."
PASSWORD_DELETED_NOTE = "Xavfsizlik uchun parolli xabar o'chirildi."

KIND_LABELS = {
    "xray": "Rentgen",
    "panorama": "Panoramik rentgen",
    "cbct": "KT",
    "photo": "Rasm",
    "document": "Hujjat",
}
MEAL_LABELS = {"before": "ovqatdan oldin", "after": "ovqatdan keyin", "with": "ovqat bilan", "any": "istalgan vaqt"}


def money(amount: Decimal) -> str:
    whole = int(amount.quantize(Decimal("1")))
    return f"{whole:,}".replace(",", " ") + " so'm"


def day_label(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def local_time(instant: datetime, zone: ZoneInfo) -> str:
    return instant.astimezone(zone).strftime("%H:%M")


def prescription(item) -> str:
    lines = [f"Retsept, {day_label(item.created_at.date())}", f"Doktor: {item.doctor.user.full_name}"]
    for line in item.items.all():
        meal = MEAL_LABELS.get(line.meal_relation, "")
        lines.append(
            f"- {line.medicine} {line.dose}: kuniga {line.times_per_day} marta, {line.duration_days} kun, {meal}"
        )
        if line.instructions:
            lines.append(f"  {line.instructions}")
    if item.notes:
        lines.append(item.notes)
    return "\n".join(lines)


def attachment_caption(item) -> str:
    when = item.taken_at or item.created_at.date()
    tooth = f", tish {item.tooth}" if item.tooth else ""
    return f"{KIND_LABELS.get(item.kind, item.kind)}, {day_label(when)}{tooth}"


def procedures(items, zone: ZoneInfo) -> str:
    lines = ["Muolajalar tarixi:"]
    for item in items:
        tooth = f", tish {item.tooth}" if item.tooth else ""
        when = item.performed_at.astimezone(zone).date()
        lines.append(
            f"{day_label(when)}: {item.service.name}{tooth}, {money(item.total)} ({item.doctor.user.full_name})"
        )
    return "\n".join(lines)


def doctor(member) -> str:
    lines = [f"Doktoringiz: {member.user.full_name}"]
    if member.specialty is not None:
        lines.append(f"Mutaxassislik: {member.specialty.name}")
    if member.experience_years:
        lines.append(f"Tajriba: {member.experience_years} yil")
    clinic = member.clinic
    lines.append(f"Klinika: {clinic.name}")
    if clinic.phone_number:
        lines.append(f"Telefon: {clinic.phone_number}")
    if clinic.address:
        lines.append(f"Manzil: {clinic.address}")
    return "\n".join(lines)


def doctor_day(summary: DoctorDay, *, header: str | None = None) -> str:
    zone = ZoneInfo(summary.clinic.timezone)
    lines = [header or f"{summary.clinic.name}, {day_label(summary.day)}"]
    lines.append(f"Yangi bemorlar: {summary.new_patients}")
    lines.append(f"Muolajalar: {summary.procedures}")
    lines.append(f"Kutayotgan uchrashuvlar: {len(summary.waiting)}")
    for visit in summary.waiting:
        service = f", {visit.service.name}" if visit.service is not None else ""
        lines.append(f"  {local_time(visit.start_at, zone)} {visit.patient.full_name}{service}")
    return "\n".join(lines)


def doctor_morning(summary: DoctorDay) -> str:
    zone = ZoneInfo(summary.clinic.timezone)
    count = len(summary.waiting)
    if count == 0:
        return f"Xayrli tong! Bugun ({summary.clinic.name}) sizda uchrashuv yo'q."
    lines = [f"Xayrli tong! Bugun sizni {count} ta uchrashuv kutmoqda ({summary.clinic.name}):"]
    for visit in summary.waiting:
        lines.append(f"  {local_time(visit.start_at, zone)} {visit.patient.full_name}")
    return "\n".join(lines)


def _branch(row: BranchDay) -> list[str]:
    return [
        f"Yangi bemorlar: {row.new_patients}",
        f"Muolajalar: {row.procedures} ta, {money(row.procedures_sum)}",
        f"Bugun to'langan: {money(row.collected)}",
        f"Jami qarz (to'lanishi kerak): {money(row.debt)}",
        f"Uchrashuvlar: {row.appointments} ta, bajarildi {row.appointments_completed}, "
        f"kutmoqda {row.appointments_waiting}",
    ]


def owner_report(day: date, rows: list[BranchDay]) -> str:
    lines = [f"Kunlik hisobot, {day_label(day)}"]
    for row in rows:
        lines += ["", row.clinic.name, *_branch(row)]
    if len(rows) > 1:
        total = BranchDay(
            clinic=None,
            new_patients=sum(r.new_patients for r in rows),
            procedures=sum(r.procedures for r in rows),
            procedures_sum=sum((r.procedures_sum for r in rows), Decimal("0")),
            collected=sum((r.collected for r in rows), Decimal("0")),
            debt=sum((r.debt for r in rows), Decimal("0")),
            appointments=sum(r.appointments for r in rows),
            appointments_completed=sum(r.appointments_completed for r in rows),
            appointments_waiting=sum(r.appointments_waiting for r in rows),
        )
        lines += ["", "Barcha filiallar", *_branch(total)]
    return "\n".join(lines)
