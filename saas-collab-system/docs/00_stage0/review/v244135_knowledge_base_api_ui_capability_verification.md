# V2.44.135 内部系统数据接口界面与能力验证

验证日期：2026-09-21  
验证环境：本地 Vite Mock，`http://127.0.0.1:4174`  
验证路由：`/integrations/ai-open-api`

## 1. 验证结论

界面增量通过，端到端对接能力未完成。

- “API数据接入 → 内部系统数据接口”菜单可见且只有一个入口。
- 路由跳转、面包屑、四个页签及页面内容正常。
- 页面未提供新增、修改、删除、审批、发布、任务触发或凭据生成操作。
- 路由要求内部用户同时具备 `config.system.manage` 和 `config.view`。
- 后端尚未发现统一只读 API、独立服务身份、资源/字段白名单或双层写方法拒绝实现。
- 因此本版本只能验收“菜单、权限入口和只读原则说明”，不能验收“知识库或其他内部系统已可调用 API 读取数据”。

## 2. 验证结果

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 菜单唯一入口 | 通过 | API数据接入下显示“内部系统数据接口” |
| 受保护路由 | 通过 | `/integrations/ai-open-api`，仅 internal 且要求两项配置权限 |
| 读写边界 | 通过 | 明示 GET/HEAD/OPTIONS；POST/PUT/PATCH/DELETE 拒绝 |
| 数据合同展示 | 通过 | 展示租户、更新时间、删除标记、版本、哈希和游标字段 |
| 安全要求展示 | 通过 | 展示服务身份、白名单、来源网络及审计要求 |
| 实施状态展示 | 通过 | 明确服务身份、授权模型和只读 API 待后端实现 |
| 页面写入控件 | 通过 | 页面源码不存在 `el-input`、`el-button` 业务操作控件 |
| 定向自动化测试 | 通过 | `3 passed` |
| 前端生产构建 | 通过 | Vite build 成功 |
| 浏览器控制台 | 有非阻断项 | 仅 `favicon.ico` 404 |
| 通用只读 API | 未通过 | 后端未发现 `/api/internal-readonly/v1/` 或等价实现 |
| 服务账号与凭据 | 未通过 | 页面明确标记待后端实现 |
| 真实数据读取 | 未验证 | 当前使用 Mock，且不存在本次接口后端实现 |
| 虚拟机/阿里云部署 | 未验证 | 本轮仅本地界面验证 |

## 3. 浏览器证据

- `frontend/output/playwright/knowledge-base-api-boundary.png`
- `frontend/output/playwright/knowledge-base-api-contract.png`
- `frontend/output/playwright/knowledge-base-api-security.png`
- `frontend/output/playwright/knowledge-base-api-delivery.png`

## 4. 自动化命令

```text
npm test -- --run tests/knowledge-base-api-menu.spec.js
npm run build
```

结果：定向测试 3/3 通过，生产构建成功。

## 5. 能力验收缺口

要达到“内部其他系统或知识库可以自行配置并读取数据”，至少还需完成：

1. 独立服务身份和可轮换凭据。
2. `/api/internal-readonly/v1/` 统一入口及 OpenAPI 合同。
3. 租户、资源、字段、时间范围和来源 IP/CIDR 白名单。
4. 路由层与权限层双重拒绝写方法。
5. 游标分页、增量水位、删除传播、限流和幂等字段。
6. 请求审计及敏感字段脱敏。
7. 虚拟机联调、阿里云部署和真实服务身份验收。

在这些缺口关闭前，不应向调用方发放生产凭据，也不应把页面状态标记为“已具备对接能力”。
