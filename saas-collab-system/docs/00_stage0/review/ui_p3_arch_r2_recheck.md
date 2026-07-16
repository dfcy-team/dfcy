# UI-P3-ARCH-R2 RPA任务与设备基础整改复审报告

## 1. 复审对象

- 项目：`saas-collab-system/`
- 分支：`feature/ui-p3-rpa-task-device-foundation`
- 当前HEAD：`ffdffed`之上的整改工作树
- 复审日期：2026-07-16
- 原报告：`docs/00_stage0/review/ui_p3_arch_r1_recheck.md`
- 原结论：`CONDITIONAL_PASS`
- 原P1：运行记录组合custom scope放宽；稳定性Mock双状态机合同不完整

R2只复核整改结果及相关回归范围，不覆盖或修改R1原始审核记录。

## 2. 复审结论

**PASS**

- P0：无。
- P1：无，原2项P1均已关闭。
- P2：4项，不阻断UI-P3收尾。

UI-P3页面、API、permission-specific data_scope、任务/运行双状态机、设备dry-run及安全边界通过R2复审，建议进入提交、PR和UI-P3收尾流程。

## 3. 原P1关闭情况

| 原问题编号 | 问题 | 是否关闭 | 证据 | 备注 |
|---|---|---|---|---|
| UI-P3-R1-P1-001 | 运行记录同时配置任务与设备custom scope时使用OR，扩大tenant内可见范围 | 是 | `backend/apps/rpa/internal_scope.py`、`backend/tests/test_ui_p3_rpa_management.py` | 单scope内任务/设备维度取交集，多角色scope之间取并集 |
| UI-P3-R1-P1-002 | 稳定性Mock含非法`retry_wait`且缺少`run_states` | 是 | `frontend/src/mock/rpaStability.js`、`frontend/tests/ui-p3-rpa-task-device.spec.js` | 已使用`retrying`并显式返回任务/运行两组状态 |

## 4. data_scope整改复审

结论：**PASS**。

- 每个custom scope独立构造运行记录过滤条件。
- scope配置`rpa_task_ids`时约束任务维度。
- scope配置`rpa_device_ids`时约束设备维度。
- 同一scope同时配置两类维度时使用AND，不再任一命中即放行。
- 多个授权角色/scope之间使用OR，保留正常的角色授权并集。
- scope没有有效任务或设备ID时返回空集，不默认放行。
- 所有查询仍先按当前tenant过滤。

新增测试实际覆盖：

1. 任务和设备均在同一授权scope时可见。
2. 任务允许但设备不允许时不可见。
3. 设备允许但任务不允许时不可见。
4. 两个授权角色各自合法的运行记录均可见，跨角色拼接组合不可见。

## 5. 双状态机Mock整改复审

结论：**PASS**。

- `retry_wait`已删除，统一使用冻结状态`retrying`。
- 稳定性Mock显式提供`task_states`。
- 稳定性Mock显式提供`run_states`。
- `manual_required`汇总字段与后端结构一致。
- `boundary=internal_read_only_no_agent_execution`明确管理端只读边界。
- 前端测试分别以任务状态集合和运行状态集合校验Mock，禁止合同外状态。
- 浏览器复核显示任务状态机和运行状态机均有独立数据，未出现`retry_wait`，无页面级横向溢出。

## 6. 页面、API与权限回归

结论：**PASS**。

- 任务、运行、设备、人工队列、稳定性、账号锁和页面签名路由合同保持不变。
- internal管理端继续只调用`/api/internal/rpa/*`。
- 前端扫描未发现Agent claim、heartbeat、logs、screenshots、complete或fail请求。
- external和RPA用户不能访问internal管理接口。
- 人工分配、Mock重试和设备dry-run继续要求独立动作权限。
- 401/403/404/409/422不回退Mock。
- 未登记的非公开路由继续默认拒绝。

## 7. 设备与dry-run回归

结论：**PASS**。

- 设备模式仍限制为`mock/dry_run/production_disabled`。
- `production_disabled`继续拒绝dry-run和Agent claim。
- dry-run不启动浏览器、不访问平台，平台连接和浏览器自动化固定为`not_attempted`。
- 设备响应不返回Token、IP白名单或完整设备指纹。
- 未新增真实RPA脚本、真实选择器或真实平台连接。

## 8. 独立测试与构建

| 检查 | R2结果 | 证据 |
|---|---|---|
| Django check | PASS | System check identified no issues |
| migration一致性 | PASS | No changes detected |
| UI-P3专项pytest | PASS | 12 passed in 9.90s |
| 全量pytest | PASS | 283 passed in 27.19s |
| UI-P3专项Vitest | PASS | 1 file，9 tests passed |
| 全量Vitest | PASS | 5 files，78 tests passed |
| 前端生产构建 | PASS | 1909 modules transformed，4.59s |
| Docker配置 | PASS | 配置可解析；本机未注入部署变量，存在缺省值提示 |
| RPA JSON | PASS | 16个JSON文件有效 |
| 稳定性页面实测 | PASS | task/run两组状态存在，`retry_wait`不存在，无横向溢出 |

## 9. 安全扫描

结论：**PASS**。

- 未发现被跟踪的真实`.env`、私钥或证书。
- 未发现真实账号、密码、Token、Cookie、Session、API Key或API Secret。
- 未发现真实BigSeller、Shopee、TikTok/TK连接。
- 未发现管理前端调用Agent执行端点。
- 未启用自动改价、刊登、清仓、补货或财务操作。
- `frontend/dist`和`node_modules`未被跟踪；RPA cache/downloads仅保留`.gitkeep`。

## 10. P0

无。

## 11. P1

无。R1两项P1均已关闭。

## 12. P2

1. 当前成果仍在未提交工作树中，创建PR前需提交并以最终HEAD确认文件范围。
2. 浏览器真实认证态API E2E尚未执行，后续应使用受控Pilot账号和隔离数据补充。
3. 前端构建存在第三方`@vueuse/core` PURE注释位置提示，不阻断本次构建。
4. Docker配置检查使用未注入部署变量的本地环境，缺省变量提示不代表Pilot部署验证完成。

## 13. 是否建议UI-P3收尾

**建议。**

UI-P3原P1已全部关闭，无新增P0/P1，专项与全量测试、构建、页面复核和安全扫描均通过。建议提交当前UI-P3实现与R1/R2审核记录，创建PR并等待远端CI；CI成功且PR文件范围未发生未经复审的变化后，可使用merge commit合并到`main`。

UI-P3 PASS不代表允许真实平台接入或真实RPA自动化。真实BigSeller、Shopee、TikTok/TK连接、真实凭据、自动改价、刊登、清仓、补货和财务操作仍必须另行专项安全评审。
