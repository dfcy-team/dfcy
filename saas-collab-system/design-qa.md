# Supply-chain option 2 design QA

Source: selected second displayed concept, `开发交付/供应链页面与性能优化_20261018/02-document-flow.png` (1487×1058).
Implementation: real Vue components in local read-only preview, 1487×1058 desktop and 390×844 supplier mobile. VM V2.44.251 sample snapshot; actual quantities retained. Preview shell is separate from production navigation and never part of build.

## Iterations

1. P2: long procurement list pushed inline progress below fold. Fixed bounded table height (310px expanded / 560px collapsed) and narrower country/status filters. Revised capture: `05-procurement-after.png`; combined source/implementation: `06-design-comparison.png`.
2. P2: supplier mobile lists and shipment lines required horizontal scrolling to reach actions. Replaced with mobile cards, preserving desktop tables; key actions remain in drawer footer. Captures: `07-supplier-mobile-after.png`, `08-supplier-mobile-orders.png`, `09-supplier-mobile-draft.png`.
3. P2: mobile draft body overflowed horizontally. Fixed fieldset/file input constraints and attachment-only scrolling. Post-fix `10-supplier-mobile-draft-fixed.png`; browser measured drawer clientWidth=scrollWidth=359, attachment container clientWidth319/scrollWidth820. Input150 correctly showed excess50 with200 ordered/100 already shipped.

## Fidelity surfaces

- Typography: existing Element Plus / system Chinese type; headings, amounts and SKU emphasized, metadata smaller.
- Spacing/layout: selected option's tabs, compact order columns and inline four-stage progress retained; bounded scrolling preserves detail visibility. Existing operating-order tab retained as functional product requirement. Preview shell is not a replacement production sidebar.
- Colors: existing navy shell/blue actions; distinct lifecycle badges and selected row; text labels accompany color.
- Images: actual product images and authenticated click-preview preserved, lazy-loaded with four concurrent requests maximum. Source sample image absent; no substitute fabricated.
- Content: actual PH order 73 is 200 ordered /100 submitted /50 allocated /0 confirmed received; mock illustrative 130 values intentionally not copied. Arrival never means receipt. Extra SKU shown separately.

## Functional evidence

Browser: progress expansion, related batch link opens correct batch, supplier order detail, mobile registration route and unsaved quantity input. No business data submitted. Backend 80 tests passed (isolated SQLite, migrations disabled for domain regression); migration-enabled core suite 45 passed. Frontend final run: 78/78 passed across eight files. Production build passed. Final procurement route console errors: none.

## Limits

No VM deployment, no external-group send, no browser write round trip. Preview returns 423 for mutations. Read performance measurements are VM in-process server projections, not end-to-end browser timings. Keyboard/screen-reader audit and all cost/inbound write screens not comprehensively audited.

## Final comparison

`12-final-comparison.png` combines source and final implementation at the same desktop viewport; `13-progress-comparison.png` compares readable progress/relations regions. Earlier P2 findings are fixed in post-fix captures. Accepted differences: genuine VM quantities rather than illustrative numbers, existing operating-order tab, larger readable row density with internal scrolling, existing Element Plus controls instead of generated pseudo-controls, and four numeric stages rather than completion-looking numbered circles. No actionable P0/P1/P2 remains within the verified screens.

final result: passed — scoped desktop procurement and supplier mobile flows; limits above remain explicit


## User correction: option 2 fidelity revision

The previous QA acceptance was too loose: it accepted a generic progress workbench instead of the selected composition. User explicitly rejected the UI. That earlier visual acceptance is superseded by this revision.

Fixed: compact lifecycle quantities in the table header, numbered state nodes with connecting lines, labeled quantities/remaining counts below nodes, related-document box plus current-stage box, pagination between list and detail. Internal supplier-shipment page now uses the same dense list / inline numbered-flow composition instead of the legacy wide table and drawer-only inspection. Existing edit drawer, mobile supplier cards, permissions and write semantics remain.

Evidence: source `02-document-flow.png`; final desktop `17-purchase-option2-final.png`; full combined comparison `18-option2-final-comparison.png`; readable flow comparison `19-option2-flow-detail-comparison.png`; internal shipment `14-shipment-option2-revised.png`. Compared at 1487×1058. Checked typography (12px cells), layout rhythm, navy/blue palette, real product-image behavior unchanged, and actual labels/quantities. Final browser reload produced no new console errors. Internal shipment progress/read-to-edit interaction covered by regression. 47 targeted tests pass; production build passes.

Accepted product differences: existing operating-order tab and extra management actions are preserved; real sample quantities (200/100/50/0) and document IDs differ from illustrative mock values; confirmation/receipt states are never fabricated. Shipment has three process groups (supplier shipment, dispatch allocation, batch logistics), with open-sea/port/warehouse states retained inside batch logistics. Preview navigation is a local shell, not a production-menu replacement. No claim of pixel-perfect clone or deployment.

Revision result: passed for corrected procurement and internal shipment composition. Previous broader visual-pass claim is withdrawn; other cost/logistics screens are not certified as option-2 clones.


## 2026-10-18 字体统一复核

费用页实测表格继承 16px，而正文为 13px，窄窗口单号折行。现为供应链 6 个页面和供应商采购页共 7 个组件接入共享 sc2-ui 样式，覆盖抽屉、对话框，复用组件沿用该作用域。统一系统字体栈、26px 页面标题、14px 控件、13px 表格、12px 辅助文字；费用单号最小列宽 175px 并保持单行。采购页实测表格与供应商订单页均为 13px。

性能：无网络字体、无新增数据请求、无 JS 字体加载或 resize 监听，构建后的共享 CSS 1525 字节。生产构建通过。截图 25-cost-typography.png 可见费用单号恢复单行。390px 供应商 DOM 测量无横向溢出；模拟视口截图存在浏览器缩放采集异常，不能据此宣称手机真机清晰度验收。仅本地预览，未部署。


## 2026-10-18 人工订单通知
采购详情复用已读取的订单，显示可复制的单号、供应商、国家、总数量、总金额与备注单号；不包含内部备注。附件沿用现有采购 Excel / SKU PDF 下载接口，按点击生成或下载，不预加载。正式页面优先使用通知中的供应商链接，否则使用本站既有 /supplier/orders/:id 登录路由；只读预览不提供冒充正式入口的链接。独立通知页只在缺少订单 prop 时补读一个采购详情。没有通知记录也可显示人工内容，复制下载不会改变送达状态或触发自动投递。已有投递尝试时提示先核对群消息。
9 项定向前端测试通过，生产构建通过。浏览器核对正文与当前订单一致并完成复制，截图 27-manual-order-notification.png。预览未捕获二进制附件，未声称在该预览实际下载文件成功；正式系统继续沿用已有附件接口。
