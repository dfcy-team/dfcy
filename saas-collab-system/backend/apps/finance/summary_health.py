"""Sanitized, process-independent status for automatic summary checks."""
from django.utils import timezone
from .summary_models import FinanceSummaryAutomationCheck

MESSAGES = {
    'executor_inactive': ('paused', '自动更新执行账号不可用', '请管理员确认执行账号及其启用状态。'),
    'permission_denied': ('paused', '自动更新执行账号权限不足', '请管理员恢复执行账号的完整查看及汇总更新权限。'),
    'source_unavailable': ('paused', '自动更新所需的批次文件不可用', '请管理员恢复已验收批次文件，再等待下一次检查。'),
    'validation_failed': ('paused', '自动更新检查未通过', '请管理员核对批次范围及配置，再等待下一次检查。'),
    'retry_cooldown': ('waiting', '上次更新失败，正在等待下次检查', '查看汇总记录中的失败任务；系统将在后续检查时重试。'),
    'task_pending': ('pending', '已有汇总任务排队或执行中', '等待现有任务完成，避免重复提交。'),
    'queued': ('pending', '已提交自动汇总任务', '任务完成并通过校验后自动替换结果。'),
    'unchanged': ('healthy', '最近检查未发现需要更新的来源', '继续按计划检查。'),
    'version_changed': ('waiting', '检查期间批次或设置发生变化', '等待下一次检查，当前结果保持不变。'),
}


def record_check(dataset, code):
    FinanceSummaryAutomationCheck.objects.update_or_create(dataset=dataset,
        defaults={'checked_at': timezone.now(), 'code': code})


def automation_health(dataset):
    row = FinanceSummaryAutomationCheck.objects.filter(dataset=dataset).values('checked_at', 'code').first()
    checked = row['checked_at'].isoformat() if row else None
    if not dataset.metadata.get('database_scope'):
        return {'state': 'manual', 'checked_at': checked, 'message': '当前批次尚未启用数据库自动汇总', 'recovery': '请管理员核对来源接入。'}
    if dataset.metadata.get('automatic_update_enabled') is False:
        return {'state': 'disabled', 'checked_at': checked, 'message': '自动更新已关闭', 'recovery': '如需自动更新，请管理员核对并启用配置。'}
    if not row:
        return {'state': 'unknown', 'checked_at': None, 'message': '尚无此批次的自动检查记录', 'recovery': '等待下一轮检查；持续无记录请管理员检查调度服务。'}
    if (timezone.now()-row['checked_at']).total_seconds() > 900:
        return {'state': 'stale', 'checked_at': checked, 'message': '超过15分钟未记录自动检查', 'recovery': '请管理员检查调度服务和后台任务状态。'}
    state, message, recovery = MESSAGES.get(row['code'], ('unknown', '自动检查状态待核对', '请管理员检查调度服务。'))
    return {'state': state, 'checked_at': checked, 'message': message, 'recovery': recovery}
