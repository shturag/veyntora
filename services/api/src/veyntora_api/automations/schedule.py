"""When scheduled automations and watchers run next.

Schedules are read in their own time zone (07:45 Europe/Berlin stays 07:45 across daylight
saving changes) and may skip public holidays of a country and state (`holidays` package,
offline). Times are stored in UTC (`automations.next_run_at`).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import holidays
from croniter import croniter
from veyntora_spec.automation import (
    Holidays,
    Repeat,
    ScheduleTrigger,
    WatcherTrigger,
    WatchEvery,
)

_DAYS = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0}
# A schedule that skips every day (holidays only) is cut off rather than searched forever.
_MAX_TRIES = 400


class ScheduleError(ValueError):
    pass


def cron_of(trigger: ScheduleTrigger | WatcherTrigger) -> str:
    """The five-field cron expression, in the trigger's time zone."""
    hour, minute = (int(p) for p in trigger.time.split(":"))
    if isinstance(trigger, WatcherTrigger):
        return f"{minute} * * * *" if trigger.every is WatchEvery.HOUR else f"{minute} {hour} * * *"
    if trigger.repeat is Repeat.DAILY:
        return f"{minute} {hour} * * *"
    if trigger.repeat is Repeat.WEEKLY:
        days = ",".join(str(_DAYS[d]) for d in trigger.days) or "1"
        return f"{minute} {hour} * * {days}"
    if trigger.repeat is Repeat.MONTHLY:
        return f"{minute} {hour} {trigger.day_of_month} * *"
    if trigger.repeat is Repeat.HOURS:
        return f"0 */{trigger.every_hours} * * *"
    expr = (trigger.cron or "").strip()
    if len(expr.split()) != 5 or not croniter.is_valid(expr):
        raise ScheduleError("enter a valid cron expression with five fields")
    return expr


@lru_cache(maxsize=64)
def _holidays(country: str, subdivision: str | None, year: int) -> frozenset[date]:
    try:
        found = holidays.country_holidays(country, subdiv=subdivision, years=year)
    except NotImplementedError as exc:
        raise ScheduleError(f"no public holidays known for {country}") from exc
    return frozenset(found.keys())


def is_holiday(day: date, skip: Holidays | None) -> bool:
    return skip is not None and day in _holidays(skip.country, skip.subdivision, day.year)


def next_runs(
    trigger: ScheduleTrigger | WatcherTrigger, after: datetime, count: int = 3
) -> list[datetime]:
    """The next `count` run times after `after`, in UTC."""
    zone = ZoneInfo(trigger.timezone)
    skip = trigger.skip_holidays if isinstance(trigger, ScheduleTrigger) else None
    it = croniter(cron_of(trigger), after.astimezone(zone))
    out: list[datetime] = []
    for _ in range(_MAX_TRIES):
        at: datetime = it.get_next(datetime)
        if is_holiday(at.date(), skip):
            continue
        out.append(at.astimezone(UTC))
        if len(out) >= count:
            break
    return out


def next_run(trigger: ScheduleTrigger | WatcherTrigger, after: datetime) -> datetime | None:
    found = next_runs(trigger, after, 1)
    return found[0] if found else None


def in_working_hours(at: datetime, timezone: str) -> bool:
    """Monday to Friday, 07:00-19:00 local time."""
    local = at.astimezone(ZoneInfo(timezone))
    return local.isoweekday() <= 5 and 7 <= local.hour < 19
