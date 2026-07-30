# SC-F2-LABEL-FONT-2 权威中文字体候选资产取得与仓库外核验报告

## 1. 阶段结论

| 项目 | 结论 |
| --- | --- |
| 工作包 | `SC-F2-LABEL-FONT-2` |
| 执行基线 | `29b3ee1feea0cadcc87d7fc4f35b61653d5e3adf` |
| 执行环境 | 架构员 Windows 主机 + 无网络 Linux 容器 |
| 正式系统连接/写入 | 0 |
| Git 跟踪字体二进制 | 0 |
| renderer/API/领域代码修改 | 0 |
| 上游原始静态 OTF | 已取得并核验；因当前 ReportLab 不支持 CFF 而淘汰 |
| 最终仓库外候选 | `SC F2 Label Sans` Regular/Bold 静态 TrueType |
| P0/P1 | 0/0 |
| 阶段结论 | `PASS_FOR_SC_F2_LABEL_FONT_ASSET_ADMISSION_REVIEW` |

本轮已取得权威、不可变上游来源，完成下载边界、哈希、安全扫描、隔离解析、许可证用途、Reserved Font Name、静态实例化可重复性、冻结语料覆盖和当前 ReportLab 兼容性核验。最终候选只保留在仓库外专项暂存目录，不构成资产入库、renderer 实现、客户端融合、客户验收或生产授权。

下一门禁为 `SC-F2-LABEL-FONT-3` 独立资产准入审核。`SC-F2-LABEL-FONT-R1-P2-001` 和 `R1-P2-002` 继续生效。

## 2. 范围与生产隔离

仓库外暂存根目录：

`D:\Users\Administrator\Documents\saas协同系统\_sc_f2_font_staging\Sans2.004`

本轮仅执行：

- 权威 HTTPS 来源和不可变 release/commit 冻结；
- 下载到仓库外新建目录；
- 归档结构检查、SHA-256、恶意代码扫描；
- 无网络、只读输入、非特权、限资源容器内字体解析和静态实例化；
- 许可证、字体元数据、字符覆盖和 ReportLab 兼容性核验；
- 仓库外候选 manifest 生成以及本审核报告归档。

本轮没有安装或注册 Windows 字体，没有读取或写入正式 Supabase、MySQL、Redis、对象存储或打印设备，没有修改供应链线上系统、标签 renderer、API、权限、DataScope、领域状态机或发布配置。

## 3. 权威来源冻结

### 3.1 上游静态发布包

| 项目 | 冻结值 |
| --- | --- |
| 项目 | `notofonts/noto-cjk` |
| 发布页 | [Noto Sans CJK 2.004](https://github.com/notofonts/noto-cjk/releases/tag/Sans2.004) |
| release tag | `Sans2.004` |
| release ID | `58070850` |
| 发布时间 | `2022-01-27T07:11:21Z` |
| 资产 | `08_NotoSansCJKsc.zip` |
| 资产 ID | `60014078` |
| 官方下载 URL | `https://github.com/notofonts/noto-cjk/releases/download/Sans2.004/08_NotoSansCJKsc.zip` |
| GitHub API 声明类型 | `application/zip` |
| HTTP 最终响应类型 | `application/octet-stream` |
| 下载完成时间 | `2026-07-30T01:57:28.478Z` |
| 字节数 | `94,523,633` |
| SHA-256 | `a927e56f53bd6c3b920bc139c0b94aa36c7d9ad0cf009b159437a1a003581140` |

HTTP 请求返回 `200`，发生 1 次到 GitHub release asset 域的重定向。已记录响应头和最终 origin/path；带时效签名的 query 不进入仓库，完整最终 URL 取证摘要为 `7259c9ef7277cb0852c7dbf2fce33cf845edd70d4fbb3121f878bcb46a46d461`。

归档共 8 个普通文件，无绝对路径、盘符、`..`、符号链接、硬链接、reparse point 或规范化路径冲突；单文件、条目数、解包总量和压缩比均在基线阈值内，CRC 全部通过。解包总量为 `115,406,549` 字节，只提取 Regular、Bold 和 LICENSE 进入候选检查目录。

### 3.2 上游 TrueType 来源

当前 renderer 对上述静态 CFF OTF 不兼容，因此按基线“variable-to-static 视为新候选并全量重审”的规则，冻结同一家族的 Google Fonts 权威 TrueType 来源：

| 项目 | 冻结值 |
| --- | --- |
| 项目 | `google/fonts` |
| 不可变提交 | [`2894aab31764f10f29c421bdfd2340d3b382d384`](https://github.com/google/fonts/commit/2894aab31764f10f29c421bdfd2340d3b382d384) |
| 提交说明 | `Noto Sans SC hotfix2 (#5533)` |
| 源文件 | `ofl/notosanssc/NotoSansSC[wght].ttf` |
| Git blob SHA-1 | `fb0637bafbcd804fe32152370a1225990745b4bc` |
| 原始 URL | `https://raw.githubusercontent.com/google/fonts/2894aab31764f10f29c421bdfd2340d3b382d384/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf` |
| 最终 URL | 与原始 URL 相同 |
| HTTP 状态/重定向 | `200` / `0` |
| Content-Type | `application/octet-stream` |
| 下载完成时间 | `2026-07-30T02:16:09.501Z` |
| 字节数 | `17,772,300` |
| SHA-256 | `a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da` |

同一提交下许可证和元数据：

| 文件 | Git blob SHA-1 | 字节数 | SHA-256 |
| --- | --- | ---: | --- |
| `OFL.txt` | `1c9f43281b8f216c5461fe9ac729afbade7724e4` | 4,388 | `1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9` |
| `METADATA.pb` | `94723577311c60831fabdb3e0d4450d0ed6763a5` | 1,053 | `3de4c75126b7b78011abb6773dd88ca3041ab512623681bd9234ef50019afc37` |

两者 HTTP 状态均为 `200`、0 重定向，Content-Type 为 `text/plain; charset=utf-8`。未使用 `latest`、短链、网盘、第三方镜像或开发机系统字体。

## 4. 原始静态 OTF 核验与淘汰

| 文件 | 字节数 | SHA-256 | 版本 | outline | 字重 | v1 语料 |
| --- | ---: | --- | --- | --- | ---: | --- |
| `NotoSansCJKsc-Regular.otf` | 16,437,364 | `2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b` | `2.004` | CFF | 400 | 105/105 |
| `NotoSansCJKsc-Bold.otf` | 17,002,248 | `b5f0d1a190a7f9b43c310a8850630af12553df32c4c050543f9059732d9b4c0a` | `2.004` | CFF | 700 | 105/105 |
| `LICENSE` | 4,301 | `6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2` | OFL-1.1 | — | — | — |

两份 OTF 均为静态字体、`fsType=0`、允许子集化，字符覆盖通过。但在与当前依赖范围一致的 ReportLab `4.5.1` 中，Regular 和 Bold 均返回：

`TTFError: postscript outlines are not supported`

因此该路线结论为：

`REJECTED_RENDERER_INCOMPATIBLE`

不得为了沿用该资产而隐式切换 PDF 库、调用系统字体或修改当前 renderer。

## 5. TrueType 静态候选生成

### 5.1 冻结输入与工具

| 项目 | 冻结值 |
| --- | --- |
| 源字体版本 | `Version 2.004-H2;hotconv 1.0.118;makeotfexe 2.5.65603` |
| 原始形态 | TrueType variable，`wght=100..900`，默认 100 |
| Python | `3.12.13` |
| fontTools | `4.63.0` |
| fontTools wheel SHA-256 | `445af2eab030a16b9171ea8bdda7ebf7d96bda2df88ee182a464252f6e05e20d` |
| 实例化脚本 SHA-256 | `51ac9c6fe50e4a57794b9c895bdb8cf0afe8689604efd9aabb6050960be683eb` |
| 容器镜像 | `python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de` |
| 容器约束 | `--network none`、只读根和输入、UID/GID 65534、drop all capabilities、no-new-privileges、CPU/内存/PID 上限 |

生成规则：

- Regular 固定 `wght=400`；
- Bold 固定 `wght=700`；
- 删除 variable axes，输出静态 TrueType；
- 按 OFL Reserved Font Name 约束，将面向用户的主 family 改为 `SC F2 Label Sans`；
- PostScript 名分别改为 `SCF2LabelSans-Regular`、`SCF2LabelSans-Bold`；
- 保留原始 copyright、trademark、OFL 描述和 OFL URL；
- 增加不可变提交、轴值和 fontTools 版本的派生说明；
- 不覆盖原始文件。

### 5.2 可重复性

从同一只读源在两个全新输出目录独立执行两次。Regular、Bold 和 OFL 三个文件的字节数与 SHA-256 全部一致，结论为 `BYTE_IDENTICAL`。

## 6. 仓库外候选资产清单

最终候选目录：

`D:\Users\Administrator\Documents\saas协同系统\_sc_f2_font_staging\Sans2.004\derived-run-1`

| 文件 | 角色 | 字节数 | SHA-256 |
| --- | --- | ---: | --- |
| `SCF2LabelSans-Regular.ttf` | Regular / `wght=400` | 10,596,408 | `976a1010423aeb77217358385e27cdd5ea18afbac4d83c036999d5b9cacaa0b3` |
| `SCF2LabelSans-Bold.ttf` | Bold / `wght=700` | 10,585,916 | `fb03fe89d24b0b73b184a68d67dafb46132bf52e8685e7c6bfcf69863326cfe4` |
| `OFL.txt` | 原始许可证字节 | 4,388 | `1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9` |
| `manifest.json` | 仓库外候选清单 | — | `574b1973d19334987114d1fc0ff409a014e870548175cafb39ba2d8fcb407b82` |

候选 manifest schema 为 `sc-f2-label-font-candidate-manifest-v1`，状态为：

`REPOSITORY_OUTSIDE_CANDIDATE_PENDING_INDEPENDENT_ASSET_ADMISSION_REVIEW`

它不是生产 manifest，也未冻结最终 `font_bundle_digest` 算法；生产资产包位置、Git/LFS/制品策略和 bundle digest 仍由 P2-001 门禁决定。

## 7. 许可证用途核验

随源 `OFL.txt` 为 SIL Open Font License 1.1，版权声明指定 Reserved Font Name 为 `Source`。依据随包许可证和 [OFL 官方 FAQ](https://openfontlicense.org/ofl-faq/) 形成以下工程合规判断：

| 用途 | 判断 | 必须履行的条件 |
| --- | --- | --- |
| 仓库或发布制品再分发 | 允许 | 不得单独售卖字体；随副本保留 copyright 和 OFL |
| 应用/容器打包 | 允许 | 与软件一同分发并保留许可证/声明 |
| PDF 完整嵌入 | 允许 | 文档本身不因此受 OFL 约束 |
| PDF 动态子集化 | 允许 | 视为嵌入；不得移除资产包中的许可证义务 |
| variable-to-static | 允许修改 | 派生字体继续适用 OFL |
| 派生字体命名 | 不得使用 RFN `Source` 作为主字体名 | 候选主名 `SC F2 Label Sans` 不包含 `Source` |
| 上游标识 | 不得暗示 Adobe、Google 或 Noto 对本项目背书 | 保留事实性来源、版权和 trademark 元数据 |

本判断用于本地工程准入，不替代组织法务意见。独立资产准入审核仍须确认许可证文件最终交付位置和用户可见方式。

## 8. 安全、元数据与字符覆盖

### 8.1 恶意代码扫描

使用 Windows Microsoft Defender 对下载归档、提取目录、工具 wheel、原始 TrueType 和两次派生目录分别执行 Custom Scan：

| 项目 | 值 |
| --- | --- |
| Product | `4.18.26060.3008` |
| Engine | `1.1.26060.3008` |
| Signature | `1.455.402.0` |
| Signature 更新时间 | `2026-07-29 05:11:04 +08:00` |
| AntivirusEnabled | `true` |
| RealTimeProtectionEnabled | `false` |
| 显式扫描检测数 | 0 |

因实时保护未启用，本报告只依赖并明确记录每个目标的显式扫描，不把实时保护状态误写为已开启。

### 8.2 候选元数据

两份候选均满足：

- TrueType `glyf` outline；
- 静态字体，不含 `fvar`/`gvar`；
- glyph 数 `31,036`，最佳 cmap code point 数 `30,890`；
- width class 5；
- `fsType=0`，无 `no subsetting` 标志；
- family、subfamily、PostScript、weight class 与候选 manifest 一致；
- 原始 copyright、trademark 和 OFL 元数据保留；
- 主 family、typographic family 和 PostScript 名均不含 RFN `Source`。

### 8.3 冻结语料覆盖

| 项目 | 结果 |
| --- | --- |
| corpus schema | `sc-f2-label-font-corpus-v1` |
| corpus 文件 SHA-256 | `4d28a684f034a90a10d9bc4d0e0ccde8ff41435887a1de8b4de55d0e833feb6f` |
| code point 数 | 105 |
| code point 清单 SHA-256 | `18817beaf1ec51db9464fa3225ae1c1d4631801a29237c87b3bc727273975232` |
| Regular 缺字 | 0 |
| Bold 缺字 | 0 |

该结果只证明 v1 冻结语料覆盖，不扩大为 GB18030、全部简体中文、全部 CJK、繁体中文、扩展 B、私用区或 Emoji 承诺。

## 9. 当前 renderer 兼容性探针

使用 ReportLab `4.5.1` 官方 wheel：

| 依赖 | SHA-256 |
| --- | --- |
| `reportlab-4.5.1-py3-none-any.whl` | `06fce8cb56c83307cfa4909cdf4e6a2ddbb44e5d6ef4d2edca896d7e9769f091` |
| `pillow-12.3.0-...manylinux...whl` | `78cb2c6865a35ab8ff8b75fd122f6033b92a62c82801110e48ddd6c936a45d91` |
| `charset_normalizer-3.4.9-py3-none-any.whl` | `68e5f26a1ad57ded6d1cfb85331d1c1a195314756471d97758c48498bb4dcdf5` |

在无网络 Linux 容器中：

- Regular 注册通过；
- Bold 注册通过；
- 两个 face 均报告 `31,036` glyph；
- 使用两种字重绘制全部 105 个冻结 code point 并保存 PDF 成功；
- 探针 PDF 为 43,487 字节，SHA-256 为 `ea074ec2f6036cd11ae85f75bfd90165eb7ed42803504cd3946327a63991de6c`。

该探针仅证明字体解析、注册、子集嵌入和保存路径可行，不是 `packing-label-v2-cjk` 布局、错误合同、事务原子性、历史重放、文本提取或视觉回归验收，也不构成 renderer 实现授权。

## 10. 复核矩阵

| 门禁 | 结果 |
| --- | --- |
| 权威域名和不可变版本 | PASS |
| 仓库外下载 | PASS |
| 响应大小上限 256 MiB | PASS |
| 归档结构和解包上限 | PASS |
| 原始/派生 SHA-256 | PASS |
| 显式恶意代码扫描 | PASS |
| 无网络非特权隔离解析 | PASS |
| 原始许可证字节保留 | PASS |
| OFL 用途/RFN/改名核验 | PASS |
| 两次实例化逐字节一致 | PASS |
| 静态 TrueType 元数据 | PASS |
| v1 语料 105/105 | PASS |
| ReportLab 4.5.1 注册和语料 PDF 探针 | PASS |
| 字体二进制进入 Git | BLOCKED_BY_P2_001 |
| renderer 实现 | BLOCKED_BY_P2_001_AND_P2_002 |
| 客户端/生产 | NOT_AUTHORIZED |

## 11. 后续门禁

下一步仅允许进入：

`SC-F2-LABEL-FONT-3 中文字体资产准入独立审核`

该审核至少需要：

1. 独立复算源文件、派生脚本、Regular、Bold、OFL 和候选 manifest 摘要；
2. 独立确认 OFL、RFN 改名和许可证最终交付位置；
3. 审核依赖精确锁定、约 20.2 MiB 字体净增量、容器/PDF/运行内存预算；
4. 决定普通 Git、Git LFS 或发布制品存储策略及离线构建、备份、校验、回滚方式；
5. 冻结生产 manifest schema 和规范化 `font_bundle_digest` 算法；
6. 通过后另行授予精确资产复制范围。

在上述审核通过并显式关闭 P2-001 前，禁止把任何 `.ttf`、`.otf`、`.ttc`、`.woff` 或 `.woff2` 文件加入 Git。在 renderer 错误合同审核并关闭 P2-002 前，禁止修改 `backend/apps/packing/labels.py` 或实现 `packing-label-v2-cjk`。
