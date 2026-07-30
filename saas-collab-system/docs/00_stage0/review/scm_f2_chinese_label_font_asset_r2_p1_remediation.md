# SC-F2 中文标签字体资产 R2 P1 整改报告

## 1. 整改对象

| 项目 | 值 |
| --- | --- |
| 工作包 | `SC-F2-LABEL-FONT-1-R2` |
| 整改项 | `SC-F2-LABEL-FONT-R2-P1-001` |
| 整改依据 | `00d3d1a5bf34` P1 整改复核 |
| 问题 | v1 语料 LF 合同没有 Git 属性保护 |
| 当前状态 | `REMEDIATED_PENDING_QUICK_RECHECK` |
| 字体资产取得授权 | 无 |

## 2. 修复

在语料所在目录新增最小作用域属性：

`docs/00_stage0/review/assets/.gitattributes`

内容：

```gitattributes
scm_f2_label_font_corpus_v1.json text eol=lf
```

该规则只影响 v1 字体语料 JSON，不改变其他文档、源码或用户工作区文件的行尾策略。随后对目标语料执行 Git 规范化；索引内容没有业务差异，说明原提交对象已经是 LF，本次只补足跨检出约束。

## 3. 修复后验证

| 检查 | 结果 |
| --- | --- |
| `git check-attr text` | `set` |
| `git check-attr eol` | `lf` |
| `git ls-files --eol` 索引 | `i/lf` |
| `git ls-files --eol` 工作树 | `w/lf` |
| 属性显示 | `attr/text eol=lf` |
| 语料规范化差异 | 0 |
| Git whitespace | 通过 |

在显式 `core.autocrlf=true` 的 Git 单文件临时检出中预验证：

- UTF-8 BOM：无；
- CRLF：无；
- JSON：可解析；
- 正向 code point：105；
- code point 清单摘要：
  `18817beaf1ec51db9464fa3225ae1c1d4631801a29237c87b3bc727273975232`；
- 检出文件 SHA-256：
  `4d28a684f034a90a10d9bc4d0e0ccde8ff41435887a1de8b4de55d0e833feb6f`。

临时检出文件验证后已删除，没有进入 Git。

## 4. 边界

- 新增字体文件：0；
- 下载、复制或安装字体：0；
- renderer/API/领域代码修改：0；
- 正式系统连接：0；
- 两项 P2 强门禁保持不变；
- 本报告不自行签发资产取得授权。

## 5. 下一步

对本整改提交执行：

`SC-F2-LABEL-FONT-R2-P1-001 快速复核`

只有快速复核同时确认属性、隔离检出、语料内容及摘要全部通过，才允许给出：

`PASS_FOR_SC_F2_LABEL_FONT_ASSET_ACQUISITION`
