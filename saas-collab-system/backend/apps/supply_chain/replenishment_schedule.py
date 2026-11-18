"""Non-working Shanghai window for automatic replenishment."""
from datetime import datetime, time
from zoneinfo import ZoneInfo
TZ = ZoneInfo("Asia/Shanghai")
START, END = time(2, 30), time(7, 30)
SCHEDULE_LABEL = "每日北京时间02:30–07:30"
DAILY_QUEUE = "replenishment-daily"
DAILY_CHUNK_SIZE = 1000
DAILY_HARD_LIMIT, DAILY_LEASE_SECONDS = 600, 660

def in_night_window(now):
    return START <= now.astimezone(TZ).time() < END

def night_deadline(now):
    return datetime.combine(now.astimezone(TZ).date(), END, tzinfo=TZ)

def daily_task_budget(now):
    if not in_night_window(now):
        return 0
    return max(0, min(DAILY_HARD_LIMIT, int((night_deadline(now) - now).total_seconds()) - 5))
