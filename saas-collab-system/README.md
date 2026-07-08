# saas-collab-system

SaaS collaboration system monorepo.

## Project Structure

```text
saas-collab-system/
├── backend/              # Django REST Framework backend
├── docker-compose.yml    # Local development services
└── .env.example          # Example environment variables
```

Current stage focuses on the backend foundation:

- tenant and account models
- role, permission, and data scope models
- RPA task center models and placeholder APIs
- API sync center models and Celery setup
- audit log and attachment models
- internal JWT authentication APIs
- unified response and error handling
- pytest baseline

## Backend

See `backend/README.md` for local Python, Docker Compose, MySQL, Redis, Celery, migrations, and pytest commands.

## Environment

Copy `.env.example` to `.env` for local development and replace every `change-me-*` value. Never commit `.env`.

Production safety:

- Do not expose MySQL or Redis to the public internet.
- Use private networking, firewall rules, and managed secrets in production.
- Do not store real API keys, tokens, passwords, or object storage credentials in source control.

## 项目目录规范

本项目根目录固定为：

```text
saas-collab-system/
```

目录用途：

- `backend/` 后端 Django 服务、API、权限、RPA 接口、API 同步框架。
- `frontend/` 前端 Vue3 后台、业务页面、Mock 数据。
- `rpa-agent/` RPA Agent、BigSeller 操作步骤、任务样例、截图和日志目录。
- `docs/` 阶段0文档、架构、数据库、API、RPA、测试、发布文档。
- `docker-compose.yml` 用于本地开发环境编排。
- `.env.example` 用于示例环境变量，不包含真实密钥。

约束：

1. 所有新增文件必须放在 `saas-collab-system/` 内。
2. 禁止在项目根目录外创建项目文件。
3. 禁止提交真实 `.env`。
4. 禁止提交真实账号、密码、Token、API 密钥。
5. RPA 不得直连数据库。
6. 前端不承载真实权限判断。
7. 阶段0只做目录、文档、Mock、占位和底座准备。
