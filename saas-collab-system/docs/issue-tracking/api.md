# 事项跟踪 API

前缀 `/api/internal/issue-tracking/`。登录内部账号，响应遵循 `success/code/message/data`。

- GET/POST issues/：列表、发起；列表参数 view=created|assigned|collaborating|managed，status, department, assignee, menu_key, record_type, record_id, search, overdue=true。
- GET issues/{id}/：详情及 events、attachments、permissions。
- POST issues/{id}/actions/：action,content；操作 feedback,submit,return,close,reopen,reassign,reschedule,transfer,remind。附加字段分别为 close_reason(completed|cancelled|unnecessary)、assignee、due_at、department。
- POST issues/{id}/attachments/：multipart file，10MB上限；GET attachments/{id}/download/：权限校验后的下载。
- GET candidates/：users,departments,rules；GET summary/：pending,processing,confirming,overdue,items。
- GET notifications/；POST notifications/ {id} 标记已读。
- grants/、rules/：配置CRUD，仅超级管理员或 issue_tracking.configure 授权人。

事项输入：title,description,assignee,collaborators[],department,due_at,menu_key,page_path,record_type,record_id,record_number。状态 pending/processing/confirming/closed。

授权：user,department,include_descendants,permissions[],starts_at,ends_at。
规则：menu_key,enabled,screenshot_enabled,default_assignee,candidate_departments[],default_due_hours,reminder_interval_minutes。

列表data为{count,results,page,page_size}，status=open筛选未关闭。candidates含can_manage/can_configure及users[].department_ids；rules.scope=page|record|both。
