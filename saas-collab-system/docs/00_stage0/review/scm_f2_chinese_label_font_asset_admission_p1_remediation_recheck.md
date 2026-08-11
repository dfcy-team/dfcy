# SC-F2-LABEL-FONT-3 P1 整改复核报告

## 1. 复核结论

| 项目 | 结论 |
| --- | --- |
| 工作包 | `SC-F2-LABEL-FONT-3-R1-RECHECK` |
| 原独立审核提交 | `1101966e0e97a7aef7531bd6a518f6b84b60fa53` |
| 整改提交 | `807bddf0de4d2c73841970a337d4eba682d77761` |
| 分支 | `codex/scm-f2-packing-local` |
| P0 | 0 |
| 已关闭 P1 | `SC-F2-LABEL-FONT-R3-P1-001` |
| 未关闭 P1 | `SC-F2-LABEL-FONT-R3-P1-002` |
| P2-001 | `DUE_AND_BLOCKING`，关闭决定尚未生效 |
| P2-002 | `ACCEPTED_DEFERRED_WITH_PRE_RENDERER_CONTRACT_GATE` |
| 最终结论 | `REQUIRES_SC_F2_LABEL_FONT_R3_P1_002_COMPLETION` |
| 字体进入 Git | 不允许 |
| renderer 实现 | 不允许 |
| 客户端/生产 | 不允许 |

候选 manifest v2、许可证最终路径、字体元数据、覆盖合同、空授权集合和阻断状态均达到 `R3-P1-001` 的关闭条件，该项关闭。

整改已经冻结普通 Git 存储方案、精确工具链、bundle digest、容量阈值和单进程探针，并通过 Windows/Linux 独立复跑。但是原审核对 `R3-P1-002` 的关闭条件明确要求 CI、Windows、Linux 同一解析证据，以及首次加载、稳态和并发内存预算。当前材料只有 Windows/Linux 实证和 CI 未来约束，也只有两页/一百页单进程内存实测；因此 `R3-P1-002` 不能关闭，`P2-001` 的关闭决定不生效。

## 2. 复核范围与隔离

整改提交只包含 11 个受控非字体文件：

- 三个字体核验/PDF 探针脚本；
- 一个固定向量测试；
- 三组最小作用域 Git 属性；
- bundle digest 固定向量；
- 工具链锁；
- P1 整改报告；
- P2-001 关闭决定。

复核开始时和复核完成前，Git 跟踪的 `.ttf`、`.otf`、`.ttc`、`.woff`、`.woff2` 文件数量均为 0。没有修改 renderer、API、权限、DataScope 或领域代码，没有连接正式数据库、缓存、对象存储、打印机或线上系统。工作区原有的 pilot、架构和发布文档改动不属于本专项，未暂存、未修改。

仓库外复核候选：

`D:\Users\Administrator\Documents\saas协同系统\_sc_f2_font_staging\Sans2.004\derived-candidate-v2`

## 3. R3-P1-001 复核

### 3.1 manifest v2

复核的精确 manifest：

| 项目 | 值 |
| --- | --- |
| schema | `sc-f2-label-font-candidate-manifest-v2` |
| bundle ID | `sc-f2-label-font-v1-candidate-2` |
| 字节数 | 5,113 |
| SHA-256 | `e00920a6188621eb80c551a1c380ede83b46f29b23fb6e4ef79c7efcb83dcf46` |
| 状态 | `REMEDIATED_PENDING_R3_RECHECK` |

逐项确认：

- 冻结 Google Fonts 不可变 commit、源路径、URL、blob、字节数和 SHA-256；
- `LICENSE.txt` 映射到上游 `OFL.txt`，二者字节数和 SHA-256 相同；
- Regular/Bold 逐资产冻结 family、subfamily、full name、PostScript、font version、weight、width 和 outline；
- 逐资产冻结 `fsType=0`、`INSTALLABLE_EMBEDDING`、允许子集化和非 bitmap-only 语义；
- 冻结覆盖工具、fontTools `4.63.0`、wheel 摘要、脚本摘要和 v1 corpus；
- 冻结 renderer/layout 为空集合；
- 授权状态为 `BLOCKED_PENDING_R3_RECHECK_AND_R1_P2_002`；
- 下一门禁仍指向本次整改复核，没有提前授权消费者。

### 3.2 精确四文件复核

| 文件 | 字节数 | SHA-256 | 结果 |
| --- | ---: | --- | --- |
| `LICENSE.txt` | 4,388 | `1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9` | PASS |
| `SCF2LabelSans-Regular.ttf` | 10,596,408 | `976a1010423aeb77217358385e27cdd5ea18afbac4d83c036999d5b9cacaa0b3` | PASS |
| `SCF2LabelSans-Bold.ttf` | 10,585,916 | `fb03fe89d24b0b73b184a68d67dafb46132bf52e8685e7c6bfcf69863326cfe4` | PASS |
| `manifest.json` | 5,113 | `e00920a6188621eb80c551a1c380ede83b46f29b23fb6e4ef79c7efcb83dcf46` | PASS |

受控 verifier 在 Windows amd64 和 Linux amd64 均返回 PASS：

- 文件集合无缺失、无额外文件；
- Regular/Bold 全表可解析；
- 105/105 code point，缺字 0；
- 元数据和嵌入语义一致；
- bundle digest 均为 `0f1fe3ff8595b042eac0aa505c1bbc0c423822e3261e25bc7f6423f696f43ba2`；
- renderer/layout 授权保持为空。

结论：

`SC-F2-LABEL-FONT-R3-P1-001 = CLOSED_BY_RECHECK`

## 4. R3-P1-002 复核

### 4.1 已通过部分

| 检查 | 结果 |
| --- | --- |
| 普通 Git / LFS / 发布制品三选一 | `NORMAL_GIT` |
| 目标路径 | `backend/apps/packing/assets/fonts/sc-f2-label-font-v1/` |
| LFS | 禁用 |
| 运行时网络字体获取 | 禁止 |
| 字体二进制 Git 属性 | PASS，最小作用域且无 LFS filter |
| Python | `3.12.13` |
| Linux 镜像 | 不可变 digest 已冻结 |
| Python wheel | 精确版本、文件名、字节数和 SHA-256 已冻结 |
| 受控脚本 | 三个 SHA-256 与提交对象一致 |
| bundle digest | 算法、规范化规则和固定向量通过 |
| 单字体/资产包/镜像/PDF 容量阈值 | 已冻结并通过 |
| 离线构建/校验/备份/漂移/回滚 | 已冻结 |
| Windows/Linux 同一 PDF | 44,883 B，SHA-256 均为 `c3c6689a66411a2bf2dfc903285e7061d38b5e30c8560801cbb252618992a624` |
| 固定向量和脚本摘要 | 2 项合同检查通过 |

Linux 权威容器复跑：

| 探针 | 结果 |
| --- | --- |
| 两页 PDF | 44,883 B；44.922 ms；SHA-256 `c3c6689a...92a624` |
| 两页 Python allocation peak | 10,627,977 B |
| 两页 max RSS | 88,472 KiB |
| 一百页 PDF | 137,608 B；353.308 ms；SHA-256 `20017c28...783b35` |
| 一百页 Python allocation peak | 10,970,990 B |
| 一百页 max RSS | 88,332 KiB |
| FontFile2 / ToUnicode / 文本提取 | PASS |

Windows 锁定 Python/wheel 复跑：

| 探针 | 结果 |
| --- | --- |
| manifest / 字体 / corpus / bundle digest | PASS |
| 两页 PDF | 44,883 B；33.0 ms；SHA-256 `c3c6689a...92a624` |
| 两页 Python allocation peak | 10,633,029 B |
| FontFile2 / ToUnicode / 文本提取 | PASS |

### 4.2 未满足的关闭条件

#### A. 缺少 CI 同解析实证

原关闭条件要求“提供 CI、Windows、Linux 的同一解析证据”。当前锁文件只记录 Windows/Linux 结果，关闭决定只规定：

`CI 必须复用 Linux 权威镜像 digest 和锁定 wheel`

这是未来执行规则，不是已经产生的 CI 解析证据。仓库内也没有受控 CI 入口、运行记录或可校验结果证明 CI 已按 `--no-index --no-deps`、无网络和锁定摘要执行相同 verifier/PDF 探针。

#### B. 缺少首次加载、稳态和并发内存阈值与实测

原关闭条件要求冻结并验证“首次加载、稳态和并发内存预算和失败阈值”。当前锁文件只有：

- 单次进程 `python_tracemalloc_peak_max_bytes`；
- 单次进程 `standalone_probe_process_max_rss_kib`；
- 验证容器总内存限制；
- 两页和一百页单进程实测。

关闭决定进一步把并发 worker 和真实标签测量延后到 renderer 阶段。该延后与原 P2-001 的“资产提交前强门禁”不一致，也没有分别给出首次字体注册、同进程稳态重复渲染、指定并发数聚合 RSS 的阈值、测量方法和安全失败判断。

结论：

`SC-F2-LABEL-FONT-R3-P1-002 = OPEN`

## 5. P2-001 关闭决定复核

拟定决定：

`CLOSE_WITH_NORMAL_GIT_AND_TOOLCHAIN_LOCK_V1`

普通 Git 选择、离线构建、摘要校验、备份、漂移和回滚合同本身可接受。但是该决定声明只有本次复核通过后才生效，而 `R3-P1-002` 尚未关闭。

因此本轮状态保持：

`SC-F2-LABEL-FONT-R1-P2-001 = DUE_AND_BLOCKING`

不得把拟定决定的“精确四文件资产提交”权限视为已经生效。

## 6. P2-002 与安全边界

`SC-F2-LABEL-FONT-R1-P2-002` 保持：

`ACCEPTED_DEFERRED_WITH_PRE_RENDERER_CONTRACT_GATE`

本轮没有审核用户不支持字符、服务端资产故障、稳定错误码、事务回滚、同 key 重试和历史重放失败语义，因此即使后续 P2-001 关闭，也仍不得：

- 修改 `backend/apps/packing/labels.py`；
- 启用 `packing-label-v2-cjk`；
- 实现或接入中文 renderer；
- 进行客户端融合、客户验收或生产部署。

## 7. 剩余整改要求

只需继续整改 `SC-F2-LABEL-FONT-R3-P1-002`：

1. 增加受控、可由 CI 直接执行的权威 Linux 核验入口，固定镜像 digest、wheel 摘要、`--no-index --no-deps`、无网络、只读输入和资源限制；
2. 在实际 CI 环境执行该入口，归档可校验的依赖解析、verifier、PDF 摘要和预算结果；
3. 增加受控内存探针，分别测量首次字体注册/首次渲染、同进程稳态重复渲染，以及明确并发数下的聚合/单 worker 峰值；
4. 在工具链锁中分别冻结三类内存的预算、实测、并发度和超限安全失败动作；
5. Windows、Linux、CI 三端重新复核依赖版本、字体包摘要和固定 PDF 摘要一致；
6. 更新 P2-001 关闭决定和整改报告，但不得提前把字体复制进 Git。

## 8. 下一步

下一步只允许：

`补齐 SC-F2-LABEL-FONT-R3-P1-002 的 CI 同解析实证与首次/稳态/并发内存门禁，并执行快速复核`

快速复核通过前继续禁止字体二进制进入 Git/LFS/发布制品，禁止 renderer、客户端和生产实现。
