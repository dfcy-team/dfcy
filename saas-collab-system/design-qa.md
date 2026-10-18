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
