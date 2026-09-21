# V2.44.133 飞书协同候选登记说明

## 基线与范围

- 父代码基线：`v2.44.132-deployed` / `91f4df7079c26b71bc5e2a5964ab90fe95eee00f`
- 候选范围：在“API数据接入”下增加“飞书协同”，提供应用连接、身份映射、消息与预警、报表推送、审批映射、运行与事件六个页签。
- 真实飞书外部调用保持关闭；本版本只交付租户隔离的配置与治理底座。
- 不包含原开发工作树中的其他产品、仓库、刊登或广告改动。

## 受控基线变化

- 菜单：104 → 105
- 路由：136 → 137
- 权限目录：新增 `feishu.view`、五类配置管理权限及运行查看/重试权限。
- 数据库迁移：`integrations.0031_feishu_collaboration`、`permissions.0045_register_feishu_permissions`。
- 凭据：App Secret、Verification Token、Encrypt Key 仅保存 custody 引用，API 不回显明文。

## 验收结果

- `python manage.py check`：通过。
- `python manage.py makemigrations --check --dry-run`：无遗漏。
- `python manage.py test apps.integrations.tests.test_feishu_api`：4/4 通过。
- 飞书、菜单和 API 接入前端回归：13/13 通过。
- `npm run build`：通过，菜单权限快照为 105 项菜单、137 项路由。
- `git diff --check`：通过。

## 登记前置条件

1. 虚拟机 unified/shared 双账本必须均已登记为 `2.44.132`，且提交为 `91f4df7079c26b71bc5e2a5964ab90fe95eee00f`。
2. 构建并锁定前后端镜像 digest，完成数据库备份。
3. 应用两项迁移并核对迁移摘要。
4. 验证运行容器 revision、菜单/路由/权限快照、健康检查及回滚材料。
5. 由架构员执行生产登记；父版本不一致时必须失败关闭。

