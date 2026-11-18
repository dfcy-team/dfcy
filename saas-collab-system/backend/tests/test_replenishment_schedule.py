from datetime import datetime, timezone

import pytest

from apps.supply_chain.replenishment_schedule import daily_task_budget, in_night_window


@pytest.mark.parametrize(("instant", "allowed", "budget"), [
    ("2026-11-17T18:29:59+00:00", False, 0),
    ("2026-11-17T18:30:00+00:00", True, 600),
    ("2026-11-17T23:29:00+00:00", True, 55),
    ("2026-11-17T23:30:00+00:00", False, 0),
    ("2026-11-18T02:40:00+00:00", False, 0),
])
def test_night_window_uses_shanghai_day_across_utc_midnight(instant, allowed, budget):
    now = datetime.fromisoformat(instant).astimezone(timezone.utc)
    assert in_night_window(now) is allowed
    assert daily_task_budget(now) == budget
