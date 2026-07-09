# P1-A-001 RPA后端任务协议接口变更记录

## 基本信息

- 任务编号：P1-A-001
- 任务名称：RPA后端任务协议占位接口
- 执行分支：feature/phase1-a-backend-mvp-api
- 执行目录：saas-collab-system/

## 准入检查

- 当前分支已确认不是 main。
- 当前分支已确认是 feature/phase1-a-backend-mvp-api。
- 当前分支已确认基于 origin/main。
- 阶段1准入依据已确认存在：docs/00_stage0/review/ar0_010_stage0_final_review_and_phase1_entry.md。

## 输入文档

- 已参考：docs/04_rpa/rpa_api_protocol.md
- 已参考：docs/00_stage0/review/ar0_010_stage0_final_review_and_phase1_entry.md
- 未找到：docs/03_api/rpa_task_api_contract.md

说明：本次按照现有 RPA 协议文档和 AR0-010 中对 complete/fail/screenshots 的阶段1要求实现；缺失的 API contract 文档未在本任务中补建，避免越过用户指定输出范围。

## 本次变更

### backend/apps/rpa/

- 补齐 POST /api/rpa/tasks/claim/
  - 按 tenant 查询 pending 任务。
  - 支持 queue_key 占位过滤。
  - 将任务从 pending 更新为 claimed。
  - 记录 claimed_by 和 claimed_at。

- 补齐 POST /api/rpa/tasks/{id}/heartbeat/
  - RPA Agent 上报心跳。
  - claimed/pending 任务进入 running。
  - 返回 server_time 与 continue_running。

- 补齐 POST /api/rpa/tasks/{id}/logs/
  - 写入 RPATaskStepLog。
  - 不修改业务数据。

- 新增 POST /api/rpa/tasks/{id}/screenshots/
  - 阶段1仅记录截图占位信息到 RPATaskStepLog。
  - 不接外部对象存储。
  - 不提交真实截图文件。

- 补齐 POST /api/rpa/tasks/{id}/complete/
  - 仅回写 RPA 执行结果。
  - 将任务状态更新为 success。
  - 不做商品、采购、财务等业务判断。

- 补齐 POST /api/rpa/tasks/{id}/fail/
  - 支持 manual_required。
  - 支持 manual_reason、failed_step、last_success_step。
  - manual_required=true 时任务进入 manual_required。
  - 支持 retrying 占位状态。

## 权限边界

- 所有 RPA 执行接口继续使用 IsRPAAgent。
- 未使用 IsInternalUser 替代 RPA 权限。
- RPA 接口未访问 finance、internal finance 或 admin。
- RPA 任务仍通过 business_type + business_id 弱关联业务对象。
- 未连接 BigSeller、Shopee、TikTok 或其他真实平台。
- 未写入真实密钥、账号、Token、API Key 或真实截图。

## 测试覆盖

- RPA Agent 可以访问 claim。
- RPA Agent 可以访问 heartbeat/logs/screenshots/complete/fail。
- internal 普通用户不能访问 RPA Agent 执行接口。
- external 用户不能访问 RPA Agent 执行接口。
- unauthenticated 不能访问 RPA Agent 执行接口。
- complete/fail 状态流转基础测试。
- RPA 用户不能访问 finance health 接口。

## 验证记录

```powershell
cd saas-collab-system/backend
python manage.py check
pytest tests/test_rpa_models_api.py
pytest
```

执行结果：

- python manage.py check：通过，System check identified no issues。
- pytest tests/test_rpa_models_api.py：通过，11 passed。
- pytest：通过，62 passed。

备注：PowerShell 下直接执行 `pytest tests/test_rpa*` 未展开通配符，改用明确文件名 `tests/test_rpa_models_api.py` 完成等价验证。
