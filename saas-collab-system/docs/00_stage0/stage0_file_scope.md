# 阶段0文件范围说明

## 1. 项目根目录说明

- 本项目根目录固定为 `saas-collab-system/`
- 所有后端、前端、RPA、文档、测试、部署文件必须放在该目录下
- 禁止在项目根目录外创建项目文件

## 2. 开发A允许修改范围

允许：

- `backend/`
- `docker-compose.yml`
- `.env.example`
- `README.md`
- `docs/02_database/`
- `docs/03_api/`
- `docs/05_test/`
- `docs/06_release/`

禁止：

- `frontend/` 业务代码
- `rpa-agent/` 业务脚本
- 真实平台API密钥
- 真实账号密码

## 3. 开发B允许修改范围

允许：

- `frontend/`
- `rpa-agent/`
- `docs/00_stage0/`
- `docs/04_rpa/`
- `README.md`

禁止：

- `backend/` 核心代码
- 数据库模型
- 后端权限逻辑
- 真实API接入
- 真实BigSeller账号密码

## 4. 架构人员允许修改范围

允许：

- `docs/`
- `README.md`
- `.gitignore`
- `.env.example`

原则上不直接修改：

- `backend/` 业务代码
- `frontend/` 业务代码
- `rpa-agent/` 业务脚本

## 5. 安全禁止项

禁止提交：

- `.env`
- 真实数据库密码
- 真实Django `SECRET_KEY`
- 真实API Key
- 真实API Secret
- 真实BigSeller账号密码
- 真实TK/Shopee Token
- 真实银行账号或流水
- 生产服务器SSH密钥

## 6. 系统边界

- API负责拿数据，不负责页面操作
- RPA负责BigSeller操作，不允许直连数据库
- MySQL沉淀最终可信数据，不暴露公网
- 前端只做展示和交互，不承载真实权限判断
- 供应商只能访问自己的任务
- 财务数据必须独立授权
- 阶段0不接真实外部平台

## 7. 阶段0允许内容

- 目录
- 文档
- Mock
- 页面占位
- 接口占位
- 测试占位
- 启动说明

## 8. 阶段0禁止内容

- 真实平台API接入
- 真实RPA自动操作
- 自动改价
- 自动清仓
- 自动补货
- 财务自动对账
- 真实业务数据提交
