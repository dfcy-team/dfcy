# SC-F2 中文标签字体资产 R2 P1 快速复核报告

## 1. 复核结论

| 项目 | 结论 |
| --- | --- |
| 工作包 | `SC-F2-LABEL-FONT-1-R2-QUICK-RECHECK` |
| 修复提交 | `4c8158a206cce78fa7e343d9dbdf508890e663ba` |
| 复核项 | `SC-F2-LABEL-FONT-R2-P1-001` |
| P0 | 0 |
| P1 | 0 |
| P2 | 2 项保持强门禁 |
| 复核结论 | `PASS_FOR_SC_F2_LABEL_FONT_ASSET_ACQUISITION` |
| 字体进入 Git | 不允许，受 P2-001 阻断 |
| renderer 实现 | 不允许，受 P2-001/P2-002 阻断 |
| 客户端/生产 | 不允许 |

`SC-F2-LABEL-FONT-R2-P1-001` 已关闭。该结论只授权按专项基线第 7.1 节在仓库外取得并审查候选字体资产，不代表字体已准入。

## 2. 修复提交范围

`4c8158a206cc` 只新增：

| 文件 | 用途 |
| --- | --- |
| `docs/00_stage0/review/assets/.gitattributes` | 只对 v1 语料冻结 LF |
| `docs/00_stage0/review/scm_f2_chinese_label_font_asset_r2_p1_remediation.md` | 保存整改证据 |

未修改语料业务内容、基线业务合同、标签代码或其他用户文件。

## 3. Git 属性复核

冻结规则：

```gitattributes
scm_f2_label_font_corpus_v1.json text eol=lf
```

复核结果：

| 检查 | 实际结果 |
| --- | --- |
| `git check-attr text` | `set` |
| `git check-attr eol` | `lf` |
| `git check-attr working-tree-encoding` | `unspecified` |
| `git ls-files --eol` | `i/lf w/lf attr/text eol=lf` |
| 语料规范化内容差异 | 0 |
| 修复提交 whitespace | 通过 |

属性文件位于 `docs/00_stage0/review/assets/`，作用域没有扩展到其他目录。

## 4. 提交对象复核

直接从修复提交读取 v1 语料 blob：

| 检查 | 结果 |
| --- | --- |
| UTF-8 BOM | 无 |
| CRLF | 无 |
| JSON | 可解析 |
| NFC 规范化样本 | 一致 |
| 正向 code point | 105 |
| code point 清单 | 与样本独立重建结果一致 |
| 清单 SHA-256 | `18817beaf1ec51db9464fa3225ae1c1d4631801a29237c87b3bc727273975232` |
| 文件 SHA-256 | `4d28a684f034a90a10d9bc4d0e0ccde8ff41435887a1de8b4de55d0e833feb6f` |

## 5. autocrlf=true 隔离检出复核

使用：

`git -c core.autocrlf=true checkout-index --temp`

从当前已提交索引临时检出目标语料，重新执行完整语料验证：

```text
isolated_autocrlf_checkout=PASS
bom=none
crlf=none
json=valid
codepoints=105
digest=18817beaf1ec51db9464fa3225ae1c1d4631801a29237c87b3bc727273975232
file_sha256=4d28a684f034a90a10d9bc4d0e0ccde8ff41435887a1de8b4de55d0e833feb6f
```

临时检出文件已删除，没有进入工作区提交。

## 6. 原 P1 总结

| 原审核项 | 最终状态 |
| --- | --- |
| R1-P1-001 首次渲染事务原子性 | `CLOSED` |
| R1-P1-002 二进制取得与解析安全 | `CLOSED` |
| R1-P1-003 机器可判定语料 | `CLOSED` |
| R1-P1-004 许可证实际用途 | `CLOSED` |
| R2-P1-001 LF Git 属性保护 | `CLOSED` |

## 7. 仍生效的 P2 强门禁

### R1-P2-001

`ACCEPTED_DEFERRED_WITH_PRE_ASSET_COMMIT_GATE`

允许在仓库外按规程取得候选；在依赖精确锁定、大小预算、Git/LFS/制品策略和跨环境证据通过前，禁止任何字体文件进入 Git，禁止 renderer 实现。

### R1-P2-002

`ACCEPTED_DEFERRED_WITH_PRE_RENDERER_CONTRACT_GATE`

在用户不支持字符、服务端资产故障、安全错误消息、同 key 重试、历史重放失败和 SC-F2-2 错误分类兼容全部冻结前，禁止 renderer 实现。

## 8. 安全与生产边界

- 字体下载、复制、安装：0；
- 字体二进制进入 Git：0；
- renderer/API/领域代码修改：0；
- 正式系统连接：0；
- 客户端融合和客户验收授权：无；
- 生产部署和生产可用声明：无。

## 9. 下一步

允许进入：

`SC-F2-LABEL-FONT-2 权威中文字体候选资产取得与仓库外核验`

下一阶段必须严格按基线第 7.1 节执行，并只在仓库外暂存候选。完成来源、许可、摘要、元数据、安全扫描和字符覆盖核验后，进入资产准入独立审核；P2-001 关闭前不得把字体复制进仓库。
