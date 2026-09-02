# 系统 V2.44.59 统一生产候选登记

- 登记日期：2026-09-03
- 生产基线：`v2.44.58-deployed`
- 基线提交：`7fd5f7f35630a10a5b88da9ae228deb9c31aee08`
- 候选分支：`codex/v24459-combined-release`
- 发布版本：`V2.44.59`
- 最终发布提交：以本候选合并到受保护 `main` 后的完整 SHA 为准

## 核定范围

本版本统一包含以下两个增量，二者必须在同一不可变镜像和同一次受控发布中交付：

1. API 数据接入生产页面闭环：平台站点、店铺授权、能力矩阵、店铺映射、商品映射、同步异常、集成审计，以及对应路由、菜单、权限标签和租户隔离审计接口。
2. 治理与试点生产执行：治理助手评估任务、试点执行任务、受控状态迁移、异步调度与补偿、权限目录扩展、页面操作闭环、独立运行器合同和生产控制材料。

不纳入本版本的其他业务模块不得因本次发布改变菜单、路由或权限目录。菜单继续以 V2.44.58 为基线，仅增加已核定的 API 数据接入节点；治理与试点复用现有入口。

## 数据库变更

- `governance.0002_assistantevaluationjob`
- `governance.0003_assistantevaluationjob_assistant_output_and_more`
- `pilot.0006_pilotexecution`
- `pilot.0007_performancerun_target_alias`
- `pilot.0008_pilotexecution_runner_deadline_at`
- `pilot.0009_alter_performancerun_error_rate`
- `permissions.0037_seed_pilot_execution_permissions`

发布必须由受控迁移服务执行上述向前迁移；回滚只切换已登记应用镜像，不自动逆向数据库迁移。

## 发布前复核

| 检查项 | 结果 |
| --- | --- |
| Django system check | PASS |
| 迁移漂移检查 | PASS，No changes detected |
| API、治理、试点、权限定向后端测试 | PASS，53 passed |
| 独立运行器单元测试 | PASS，17 passed |
| API 菜单基线、治理与试点前端测试 | PASS，67 passed |
| 前端生产构建 | PASS |
| Git 冲突与空白检查 | PASS |

合并后仍需由 GitHub Actions 重跑仓库全量质量门禁并构建带 OCI revision 的后端、前端不可变镜像；虚拟机部署后必须复核运行提交、镜像摘要、迁移状态、容器健康、菜单/权限接口和新增页面。

## 现场依赖边界

治理与试点代码纳入本版本，但真实外部执行必须在独立运行器、TLS、令牌、OpenAI 密钥文件及允许主机清单完成 owner 管理的部署配置后才可启用。依赖缺失时后端必须保持失败关闭，不得回退到明文凭据、任意 URL 或应用虚拟机内直接执行发布命令。

## 回滚点

部署前保留 V2.44.58 的后端、前端、Redis 镜像摘要和迁移摘要作为受控回滚点。若迁移、健康检查或页面复核失败，使用生产控制面的紧急回滚路径恢复 V2.44.58 应用镜像，并保留审计记录。
