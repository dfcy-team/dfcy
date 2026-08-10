# SC-F2-LABEL-FONT-R3-P1-002 补充整改报告

## 1. 整改结论

| 项目 | 结果 |
| --- | --- |
| 整改基线 | `dea899d685313a0ef9d86d501c95f0ec2f79b53b` |
| 整改项 | `SC-F2-LABEL-FONT-R3-P1-002` |
| CI 同解析实证 | `REMEDIATED_PENDING_QUICK_RECHECK` |
| 首次/稳态/并发内存门禁 | `REMEDIATED_PENDING_QUICK_RECHECK` |
| P2-001 | `REMEDIATED_PENDING_R3_P1_002_QUICK_RECHECK` |
| P2-002 | 保持强门禁 |
| 字体二进制进入 Git | 0 |
| renderer/API/领域代码修改 | 0 |
| 正式系统连接 | 0 |
| 当前结论 | `READY_FOR_R3_P1_002_QUICK_RECHECK` |

本轮补充受控 CI 入口、机器可判定 CI 证据和独立内存探针。整改不自行宣布 P1/P2-001 关闭；只有快速复核通过后，P2-001 的普通 Git 关闭决定才生效。

## 2. 受控 CI 入口

新增：

`backend/scripts/run_sc_f2_font_ci_gate.py`

入口强制检查：

- `CI=true`；
- Linux amd64；
- Python `3.12.13`；
- `SC_F2_AUTH_IMAGE` 与锁定镜像 digest 完全一致；
- Linux/any wheel 文件名、字节数和 SHA-256；
- 已安装 fontTools、ReportLab、Pillow、charset-normalizer 和 pypdf 精确版本；
- 五个受控脚本 SHA-256；
- manifest、字体、许可证、corpus 和 bundle digest；
- 两页固定 PDF SHA-256、大小和时延；
- FontFile2、ToUnicode 和文本提取；
- 一百页 PDF 大小、时延和内存；
- 首次、稳态和并发内存门禁。

入口对任一版本、摘要、环境、PDF 或预算漂移安全失败。

## 3. CI 实际执行合同

本仓库没有现成 GitHub Actions、GitLab CI 或 Jenkins 配置。本轮在架构员主机上按供应商无关 CI 入口实际执行，范围明确标记为：

`ARCHITECTURE_HOST_CONTAINER_CI_REHEARSAL`

执行边界：

| 项目 | 冻结值 |
| --- | --- |
| 环境变量 | `CI=true` |
| 镜像 | `python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de` |
| 网络 | `none` |
| 代码和候选 | 只读挂载 |
| 依赖安装 | `pip --no-index --no-deps` |
| CPU | 2 |
| 内存 | 256 MiB |
| PID | 64 |
| Python | `3.12.13` |

CI 原始机器证据：

`docs/00_stage0/review/assets/scm_f2_label_font_ci_evidence_v1.json`

| 项目 | 值 |
| --- | --- |
| 文件字节数 | 6,754 |
| SHA-256 | `018b1517ac9b805b68e181e0cd03cbd85401eccf0a1a8ca09deb6ca2a1ab45f8` |
| 结果 | PASS |
| violations | 空集合 |

## 4. Windows/Linux/CI 同解析

| 检查 | Windows | Linux | CI rehearsal |
| --- | --- | --- | --- |
| Python | 3.12.13 | 3.12.13 | 3.12.13 |
| fontTools | 4.63.0 | 4.63.0 | 4.63.0 |
| ReportLab | 4.5.1 | 4.5.1 | 4.5.1 |
| Pillow | 12.3.0 | 12.3.0 | 12.3.0 |
| manifest | PASS | PASS | PASS |
| corpus | 105/105 | 105/105 | 105/105 |
| bundle digest | `0f1fe3...43ba2` | `0f1fe3...43ba2` | `0f1fe3...43ba2` |
| 两页 PDF | 44,883 B | 44,883 B | 44,883 B |
| PDF SHA-256 | `c3c6689a...92a624` | `c3c6689a...92a624` | `c3c6689a...92a624` |

## 5. 首次、稳态和并发内存门禁

新增：

`backend/scripts/probe_sc_f2_font_memory.py`

指标定义：

- 首次：全新子进程完成 ReportLab 导入、Regular/Bold 注册和第一份 PDF 后的进程峰值 RSS；
- 稳态：同一子进程继续生成 10 份 PDF 后，相对首次当前 RSS 的增长；
- 并发：两个隔离 worker 均完成字体注册、首次和稳态渲染并保持存活时同步采样。

| 指标 | 实测 | 上限 | 结果 |
| --- | ---: | ---: | --- |
| 首次进程峰值 RSS | 88,788 KiB | 131,072 KiB | PASS |
| 稳态当前 RSS 增长 | 92 KiB | 16,384 KiB | PASS |
| 并发 worker 1 当前 RSS | 89,192 KiB | 131,072 KiB | PASS |
| 并发 worker 2 当前 RSS | 89,368 KiB | 131,072 KiB | PASS |
| 两 worker 聚合 RSS | 178,560 KiB | 229,376 KiB | PASS |
| 两 worker 加控制进程 | 201,652 KiB | 245,760 KiB | PASS |
| 容器上限 | 256 MiB | 256 MiB | PASS |

这些数值只关闭资产和基础字体探针的提交前门禁。真实 `packing-label-v2-cjk`、最大明细、多箱、Django 和业务 worker 容量仍由 P2-002 阻断并在 renderer 阶段重新审核。

## 6. 工具链锁更新

`scm_f2_label_font_toolchain_lock_v1.json` 已补充：

- CI 入口和 CI 证据路径；
- 两个新增受控脚本 SHA-256；
- 首次、稳态和并发内存预算；
- CI 实测与证据文件摘要；
- Windows/Linux/CI 三端相同 bundle digest 和固定 PDF 摘要；
- 生效条件改为 `SC-F2-LABEL-FONT-3_R3_P1_002_QUICK_RECHECK_PASS`。

## 7. 仍生效的边界

- 字体仍只在仓库外；
- 本整改提交不得包含 `.ttf`、`.otf`、`.ttc`、`.woff` 或 `.woff2`；
- 快速复核前 P2-001 不生效；
- P2-002 继续禁止 renderer；
- 不授权客户端融合、客户验收、生产部署或切流。

## 8. 下一步

执行：

`SC-F2-LABEL-FONT-R3-P1-002 快速复核`
