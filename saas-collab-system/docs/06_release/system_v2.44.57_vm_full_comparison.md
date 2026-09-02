# V2.44.57 与当前虚拟机版本全量核对及发布记录

## 1. 核对对象

- 候选版本：`V2.44.57`
- 当前虚拟机基线：`V2.44.56`
- 虚拟机应用修订：`9520346f29e3dcfa42e8ca761d39d5aa3ec8d44c`
- 核对日期：`2026-09-03`
- 发布路径：GitHub 受控生产发布工作流，不允许人工绕过备份、迁移、健康检查和回滚保护。

## 2. 虚拟机基线盘点

| 对象 | V2.44.56 实测值 |
| --- | --- |
| Backend / Celery / Celery Beat | `saas-collab-backend:v2.44.56` |
| Frontend | `saas-collab-frontend:v2.44.56` |
| Custody sidecar | `saas-collab-custody:v2.44.50` |
| Redis | `redis@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99` |
| Backend 镜像 ID | `sha256:292c512c314f7c4dd97b2cc585d5fb9fa8b51be41db516c71f9319640ef5b5b4` |
| Frontend 镜像 ID | `sha256:d486975f4ccb2b6d682ee7d5f776dba682d28cd71f49f00447ffc32839a11649` |
| Custody 镜像 ID | `sha256:cd2116019e90dd33f0b4e9f2f8fd0a3689ba1982596121fb0be15890dfb0b382` |
| Backend 文件聚合摘要 | `221c6527f81198b46267877362535983a7dff859b30490f2679bc6d80a7e0163` / 553 文件 |
| Frontend 文件聚合摘要 | `3e7f39a5470e70e54eca9e2c3a6f9118c4d0a0225bccf9b5696d07b53fdf9655` / 305 文件 |
| Django 状态 | `manage.py check` 通过 |
| 数据库迁移 | 157 项已应用；`purchasing.0005_shipping_route` 待随下次发布应用 |

`192.168.174.131:8443` 与 `192.168.2.10:8443` 的首页、静态资源和 SSH 主机指纹核对为同一应用虚拟机。

## 3. 全量内容核对

| 范围 | 结果 | 处理 |
| --- | --- | --- |
| 前期平台/API 补全快照 | 1,442 / 1,442 路径已保留 | 全部纳入候选版 |
| V2.44.56 当前运行时路径 | 867 / 867 路径已保留 | 已与当前虚拟机版本融合 |
| 历史 `deploy/pilot/releases/*` | 非运行时源码 | 作为历史证据保留，不反向覆盖现行源码 |
| 迁移图 | 分叉已通过 merge/reconcile 迁移收敛 | 新建数据库全量迁移通过；V2.44.56 数据库原位升级演练通过 |
| 页面操作闭环 | 已融合当前虚拟机页面能力与新增平台、供应链、达人、商品闭环 | 以前端全量用例和生产构建为门禁 |
| 凭据与审计 | 未将生产凭据、私钥或数据库文件纳入发布 | Custody 保持独立，最小权限、脱敏和审计边界保留 |

## 4. 发布门禁证据

| 门禁 | 预发布结果 |
| --- | --- |
| Backend `check` / `makemigrations --check` | 通过 |
| 新建数据库全量迁移 | 通过 |
| V2.44.56 原位升级演练 | 通过 |
| 权限目录一致性 | 通过 |
| Frontend Vitest | 280 / 280 通过 |
| Frontend production build | 通过，2,074 modules transformed |
| Frontend production dependency audit | 0 vulnerabilities |
| Production baseline CI | `PRODUCTION_BASELINE_CI=PASS` |
| 私密文件/凭据字面量门禁 | 通过 |
| Backend Pytest | 845 passed / 28 skipped |

## 5. 发布与回滚约束

1. 候选修订必须合入 `main`，且以 `main` 上的 40 位完整 commit SHA 发布。
2. Backend/Frontend 镜像由工作流构建并按 digest 锁定；Redis 继续使用上述不变 digest。
3. 发布前工作流生成备份，再执行迁移和健康检查；失败时使用工作流保留的上一镜像和备份回滚。
4. Custody 数据目录、主密钥、TLS 密钥和服务 token 只以宿主机只读挂载注入，不进入 Git 或镜像。

## 6. 部署后回填

| 项目 | 部署后值 |
| --- | --- |
| `main` 发布 SHA | 待工作流完成后回填 |
| 受控发布工作流 | 待工作流完成后回填 |
| Backend 镜像 digest | 待工作流完成后回填 |
| Frontend 镜像 digest | 待工作流完成后回填 |
| Redis digest | 需与基线一致 |
| Custody 镜像/数据边界 | 需与基线一致，除非发布清单明确记录变更 |
| Django 健康检查/待迁移 | 待部署后实测 |
| 页面/API 冒烟 | 待部署后实测 |
