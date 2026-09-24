# 本地极风授权后仓库编号获取

范围：仅本地 3001 / 8002；未发布到虚拟机或阿里云。

## 接口与处理

- 依据已打开的 Apifox 项目 3972134、接口 145133318：`POST /api/warehouse/getList`，空 JSON 对象获取当前 OMS 用户仓库列表。
- 使用仓库已兑换的 Access Token 和 userId，沿用受控网络出口、HTTPS、公共凭据托管和 POST 签名。不会读取或重用一次性 Token。
- 仅提取 `code`、`name`、`country`、`isAuth`，不转发联系方式、地址或原始响应。
- 单个仓库且明确授权、国家匹配时自动关联；多个仓库需操作人选择。确认时重新查询平台列表，不接受伪造编号。编号或授权标识缺失时不猜测。
- 仓库编号关联独立于 Token 兑换事务。列表失败不清除已保存的授权；已有授权可点击“获取仓库编号”重试。
- 关联保留原授权记录、Token、授权时间和一次性 Token 消费时间；编号改变会重置库存校验、停用关联任务并记录实际用户审计。运行中任务、重复编号、并发配置或凭据变化会阻断关联。
- 页面沿用现有后台组件及文字状态，未增加通用“保存仓库配置”按钮。获取列表成功不等于库存校验成功。

## 验证

- 后端 51 项通过：`test_warehouse_discovery.py`、`test_jifeng_warehouse_credentials.py`、`test_warehouse_optional_external_code.py`、`test_warehouse_authorization_preflight.py`。内存 SQLite，禁止外部网络。
- 前端 41 项通过：`subject-api-access-dialog-runtime.spec.js`、`warehouse-api-binding-closure.spec.js`、`jifeng-warehouse-form.spec.js`。
- 前端生产构建通过；保留既有 VueUse PURE 注释警告。
- 通过用户已登录的本地会话点击一次“获取仓库编号”：THCS 获取并关联服务商编号 `THTB`，国家 `TH`。
- 数据库确认授权记录 ID 7 未替换，仍 active；授权时间与一次性 Token 消费时间未改变；新增一条实际操作用户的编号关联审计；启用同步任务数为 0。
- 页面 DOM 确认显示 `THTB`、`待校验` 和“尚未完成库存只读校验”。未将截图检查计为完整视觉验收。

尚未执行本次库存只读校验或库存同步。多仓库、失败和冲突场景使用合成数据验证，不宣称真实多仓库验收通过。
