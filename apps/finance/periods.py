"""Months and date ranges on the clinic's wall clock.

Money is stored with UTC instants; a clinic closes its month at local
midnight, so every boundary here is computed in the clinic's own zone.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.tenancy.models import Clinic

MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
MAX_RANGE_DAYS = 366


def parse_month(value: str | None, field: str = "month") -> date:
    match = MONTH.match(value or "")
    if match is None:
        raise ValidationError({field: "Expected YYYY-MM."}, code="invalid")
    return date(int(match[1]), int(match[2]), 1)


def add_months(month: date, count: int) -> date:
    index = month.year * 12 + month.month - 1 + count
    return date(index // 12, index % 12 + 1, 1)


def month_of(day: date) -> date:
    return day.replace(day=1)


def clinic_zone(request) -> ZoneInfo:
    """The request's branch zone. All-branches mode uses the first branch's
    zone: an organization's branches share a country in practice."""
    clinic = getattr(request, "clinic", None)
    if clinic is None:
        clinic = Clinic.objects.filter(pk__in=request.clinic_ids).order_by("name").first()
    return ZoneInfo(clinic.timezone if clinic is not None else settings.TIME_ZONE)


def start_of(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=zone)


def local_day(instant: datetime, zone: ZoneInfo) -> date:
    return instant.astimezone(zone).date()


@dataclass(frozen=True)
class DateRange:
    """Inclusive `start`..`end` days, bucketed so a chart has a sensible number of points."""

    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def bucket(self) -> str:
        if self.days <= 31:
            return "day"
        if self.days <= 92:
            return "week"
        return "month"

    def previous(self) -> "DateRange":
        end = self.start - timedelta(days=1)
        return DateRange(end - timedelta(days=self.days - 1), end)

    def bucket_start(self, day: date) -> date:
        if self.bucket == "day":
            return day
        if self.bucket == "week":
            return day - timedelta(days=day.weekday())
        return day.replace(day=1)

    def buckets(self) -> list[date]:
        result: list[date] = []
        day = self.start
        while day <= self.end:
            start = self.bucket_start(day)
            if not result or result[-1] != start:
                result.append(start)
            day += timedelta(days=1)
        return result


def parse_range(params) -> DateRange:
    errors = {}
    values = {}
    for field in ("from", "to"):
        try:
            values[field] = date.fromisoformat(params.get(field) or "")
        except ValueError:
            errors[field] = "Expected YYYY-MM-DD."
    if errors:
        raise ValidationError(errors, code="invalid")
    result = DateRange(values["from"], values["to"])
    if result.end < result.start:
        raise ValidationError({"to": "Must not be before `from`."}, code="invalid")
    if result.days > MAX_RANGE_DAYS:
        raise ValidationError({"to": "A range covers at most one year."}, code="invalid")
    return result
