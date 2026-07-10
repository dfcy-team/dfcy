# P1-B-FIX-007 构建记录

## npm install

- 命令：`cd frontend && npm install`
- 结果：成功。
- 摘要：依赖已是最新，`found 0 vulnerabilities`。

## npm run build

### 第一次执行

- 命令：`cd frontend && npm run build`
- 结果：失败。
- 错误摘要：沙箱权限阻止 esbuild 读取 Vite 配置相关路径，报错 `Cannot read directory "../../../../..": Access is denied.` 与 `Could not resolve ".../frontend/vite.config.js"`。
- 判断：该失败为本地沙箱权限问题，不作为代码构建失败结论。

### 提升权限后执行

- 命令：`cd frontend && npm run build`
- 结果：成功。
- Vite：`v6.4.3`
- 构建输出摘要：
  - `dist/index.html`：`0.42 kB`
  - `dist/assets/index-BWAAavCU.css`：`362.70 kB`
  - `dist/assets/index-ASfmYt8k.js`：`1,134.77 kB`，gzip 后 `370.76 kB`

## Warning

- Rollup 移除了 `@vueuse/core` 中位置不合规的 `/* #__PURE__ */` 注释。
- Vite chunk size warning：部分 chunk 超过 `500 kB`。
- 是否阻断：不阻断。阶段1先记录观察，后续可由架构复审决定是否拆包。
