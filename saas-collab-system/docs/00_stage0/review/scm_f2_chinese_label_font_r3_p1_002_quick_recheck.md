# SC-F2-LABEL-FONT-R3-P1-002 快速复核报告

## 1. 复核结论

| 项目 | 结论 |
| --- | --- |
| 工作包 | `SC-F2-LABEL-FONT-3-R3-P1-002-QUICK-RECHECK` |
| 整改提交 | `7182c580a5d7c46f6820ec435353f00ef5b6a63f` |
| 原复核提交 | `dea899d685313a0ef9d86d501c95f0ec2f79b53b` |
| P0 | 0 |
| P1 | 0 |
| R3-P1-001 | `CLOSED_BY_RECHECK` |
| R3-P1-002 | `CLOSED_BY_QUICK_RECHECK` |
| P2-001 | `CLOSED_BY_SC_F2_LABEL_FONT_3_R3_P1_002_QUICK_RECHECK` |
| P2-002 | `ACCEPTED_DEFERRED_WITH_PRE_RENDERER_CONTRACT_GATE` |
| 最终结论 | `PASS_FOR_EXACT_FOUR_FILE_FONT_ASSET_COMMIT` |
| renderer 实现 | 不允许 |
| 客户端/生产 | 不允许 |

整改提交补齐了上轮唯一未关闭项：可由 CI 直接执行的同解析入口、实际 CI rehearsal 机器证据，以及首次、稳态和并发内存阈值与实测。提交后快速复核重新执行完整入口并通过，因此 `R3-P1-002` 和 `P2-001` 正式关闭。

本结论只允许下一步把已经审核的精确四文件候选包复制到批准的普通 Git 版本化目录并形成独立资产提交，不授权 renderer。

## 2. 整改提交范围

`7182c58` 只包含 9 个受控非字体文件：

| 文件 | 用途 |
| --- | --- |
| `backend/scripts/.gitattributes` | 冻结两个新增 Python 脚本 LF |
| `backend/scripts/probe_sc_f2_font_memory.py` | 首次、稳态和并发内存探针 |
| `backend/scripts/run_sc_f2_font_ci_gate.py` | 供应商无关受控 CI 入口 |
| `backend/tests/test_sc_f2_font_bundle_digest_contract.py` | CI 证据与内存门禁合同测试 |
| `docs/00_stage0/review/assets/.gitattributes` | 冻结 CI 证据 JSON LF |
| `docs/00_stage0/review/assets/scm_f2_label_font_ci_evidence_v1.json` | 第一次实际 CI rehearsal 机器证据 |
| `docs/00_stage0/review/assets/scm_f2_label_font_toolchain_lock_v1.json` | 入口、脚本、预算和证据锁 |
| `docs/00_stage0/review/scm_f2_chinese_label_font_p2_001_closure_decision.md` | P2-001 补充关闭条件 |
| `docs/00_stage0/review/scm_f2_chinese_label_font_r3_p1_002_completion.md` | 整改报告 |

核验结果：

- 字体二进制新增：0；
- renderer/API/权限/DataScope/领域代码修改：0；
- 正式系统连接：0；
- 无关工作区文件进入提交：0；
- 提交 whitespace：PASS。

## 3. 受控脚本与证据完整性

| 项目 | 结果 |
| --- | --- |
| 五个受控脚本 SHA-256 | 与工具链锁一致 |
| CI 证据字节数 | 6,754 |
| CI 证据 SHA-256 | `018b1517ac9b805b68e181e0cd03cbd85401eccf0a1a8ca09deb6ca2a1ab45f8` |
| CI 证据 `result` | PASS |
| CI 证据 `violations` | 空集合 |
| 合同自动检查 | 3 项通过 |
| 新脚本 Git 属性 | `text: set`、`eol: lf` |
| CI JSON Git 属性 | `text: set`、`eol: lf` |

## 4. 提交后 CI 快速复跑

复跑环境：

- `CI=true`；
- 架构员主机 `ARCHITECTURE_HOST_CONTAINER_CI_REHEARSAL`；
- Linux amd64；
- Python `3.12.13`；
- 不可变镜像 `python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de`；
- `--network none`；
- 锁定 wheel，`pip --no-index --no-deps`；
- 代码和候选只读；
- 2 CPU、256 MiB、64 PID。

第二次机器证据保留在仓库外复核目录：

| 项目 | 值 |
| --- | --- |
| 文件 | `quick-recheck-evidence.json` |
| 字节数 | 6,755 |
| SHA-256 | `166d340a8f6e9fe7ce26885557090067e6ede183ff1476241f2c43dc6b8d8228` |
| result | PASS |
| violations | 空集合 |

核心结果：

| 检查 | 结果 |
| --- | --- |
| manifest SHA-256 | `e00920a6188621eb80c551a1c380ede83b46f29b23fb6e4ef79c7efcb83dcf46` |
| corpus | 105/105 |
| bundle digest | `0f1fe3ff8595b042eac0aa505c1bbc0c423822e3261e25bc7f6423f696f43ba2` |
| 两页 PDF | 44,883 B |
| 两页 PDF SHA-256 | `c3c6689a66411a2bf2dfc903285e7061d38b5e30c8560801cbb252618992a624` |
| 两页时延 | 52.803 ms，低于 2,000 ms |
| 一百页 PDF | 137,608 B |
| 一百页时延 | 342.395 ms，低于 5,000 ms |
| FontFile2 / ToUnicode / 文本提取 | PASS |

Windows、Linux、首次 CI rehearsal 和提交后快速复跑的 bundle digest 与两页固定 PDF SHA-256 均一致。

## 5. 内存门禁快速复核

| 指标 | 冻结证据 | 提交后复跑 | 上限 | 结果 |
| --- | ---: | ---: | ---: | --- |
| 首次进程峰值 RSS | 88,788 KiB | 88,864 KiB | 131,072 KiB | PASS |
| 稳态当前 RSS 增长 | 92 KiB | 88 KiB | 16,384 KiB | PASS |
| 并发 worker 最大 RSS | 89,368 KiB | 89,368 KiB | 131,072 KiB | PASS |
| 两 worker 聚合 RSS | 178,560 KiB | 178,540 KiB | 229,376 KiB | PASS |
| 两 worker 加控制进程 | 201,652 KiB | 202,008 KiB | 245,760 KiB | PASS |
| 容器限制 | 256 MiB | 256 MiB | 256 MiB | PASS |

指标定义、并发度和安全失败动作均已进入机器可判定工具链锁，不再依赖文档解释。

## 6. 负向门禁

| 场景 | 结果 |
| --- | --- |
| 未设置 `CI=true` | exit 1，拒绝执行 |
| 首次 RSS 上限强制设为 1 KiB | `result=FAIL`、exit 1 |
| 受控脚本摘要漂移 | CI 入口设计为安全失败，并由合同测试复算 |
| wheel 字节数或 SHA-256 漂移 | CI 入口设计为安全失败 |

## 7. P1/P2 状态

### R3-P1-001

`CLOSED_BY_RECHECK`

状态不变。manifest v2 和精确四文件候选仍通过。

### R3-P1-002

`CLOSED_BY_QUICK_RECHECK`

原缺口“CI 同解析实证”和“首次/稳态/并发内存门禁”均已补齐并提交后重跑。

### P2-001

`CLOSED_BY_SC_F2_LABEL_FONT_3_R3_P1_002_QUICK_RECHECK`

关闭决定 `CLOSE_WITH_NORMAL_GIT_AND_TOOLCHAIN_LOCK_V1` 正式生效。下一步只允许在：

`backend/apps/packing/assets/fonts/sc-f2-label-font-v1/`

创建精确四文件普通 Git 独立资产提交。

### P2-002

继续保持：

`ACCEPTED_DEFERRED_WITH_PRE_RENDERER_CONTRACT_GATE`

它仍禁止中文 renderer、错误合同实现、客户端融合和生产发布。

## 8. 下一步

允许进入：

`SC-F2 中文字体精确四文件资产普通 Git 独立提交`

资产提交必须只包含：

- `SCF2LabelSans-Regular.ttf`
- `SCF2LabelSans-Bold.ttf`
- `LICENSE.txt`
- `manifest.json`

复制后必须再次运行 bundle verifier，且提交不得混入 renderer、客户端或其他业务改动。
