import { describe, expect, it } from 'vitest';
import { createRequire } from 'node:module';
const require=createRequire(import.meta.url);
const { split, allocateAdvertising, allocatePublicFees, allocateItems }=require('../../backend/apps/finance/summary_allocation.cjs');
const { orderLedger,itemMembers,groupMembers,dailyAdvertising,orderAttribution,attributionTotals,ignoredWarehouse }=require('../../backend/apps/finance/summary_order_ledger.cjs');
const fact=(order,kind,amount,date)=>({store_id:1,platform:'shopee',external_order_id:order,currency:'PHP',kind,amount,date,month:'2026-09',source_id:[order,kind,date].join(':'),status:'confirmed'});
describe('以订单为底座的金额分摊',()=>{
 it('未关联仓库费用不参与汇总或待核，其他未归属金额仍分区守恒',()=>{
  const s={counted:()=>true,c:{TEST_SNAPSHOT:{database:{order_dates:{'1|a':{order_id:7}}}}}};
  const rows=[fact('a','sales','100','2026-09-03'),fact('','adjustment','-9','2026-09-03'),{...fact('','warehouse_other','-20','2026-09'),store_id:null}];
  expect(orderAttribution(s,rows[0])).toBe('');expect(orderAttribution(s,rows[1])).toContain('订单');expect(orderAttribution(s,rows[2])).toContain('国家');
  expect(orderAttribution(s,fact('missing','order_fee','-1','2026-09-03'))).toContain('唯一');
  expect(ignoredWarehouse(s,rows[2])).toBe(true);expect(ignoredWarehouse(s,fact('a','warehouse_order','-2','2026-09-03'))).toBe(false);
  const totals=attributionTotals(s,rows);expect(totals.map(x=>[x.kind,x.total,x.assigned,x.pending])).toEqual([['sales','100.000000','100.000000','0.000000'],['adjustment','-9.000000','0.000000','-9.000000']]);
  const unknown=attributionTotals({...s,counted:()=>false},[fact('','adjustment',null,'2026-09-03')]);expect(unknown[0].unknown_rows).toBe(1);expect(unknown[0].total).toBe('0.000000');
 });
 it('无订单调整按公共费用在月周半月分摊，直接订单调整不重摊，仓库余额不进入账本',()=>{
  const sales=[fact('a','sales','100','2026-09-03'),fact('b','sales','100','2026-09-10')],adjustment=fact('','adjustment','-20','2026-09-11'),direct=fact('a','adjustment','5','2026-09-11');
  const parents=[...sales,adjustment,direct],s={counted:f=>f.amount!=null,p:{localFact:f=>f},c:{TEST_SNAPSHOT:{database:{shares:{unallocated:[{...fact('','warehouse_other','-99','2026-09'),store_id:null}]}}},HTML2_STORE_HIERARCHY:{setMode:()=>{},stores:()=>[],controls:()=>parents,orderAllocation:rows=>rows}}};
  const month=orderLedger(s,'month');expect(month.filter(f=>f.public_fee_evidence).map(f=>[f.external_order_id,f.amount])).toEqual([['a','-10.000000'],['b','-10.000000']]);
  expect(orderLedger(s,'week').filter(f=>f.public_fee_evidence).map(f=>[f.external_order_id,f.amount])).toEqual([['b','-20.000000']]);
  expect(orderLedger(s,'half_month').filter(f=>f.public_fee_evidence).map(f=>f.external_order_id)).toEqual(['a','b']);
  expect(month.find(f=>f.source_id===direct.source_id).amount).toBe('5');expect(month.some(f=>f.kind==='warehouse_other')).toBe(false);expect(parents[2].amount).toBe('-20');
 });
 it('成本快照已唯一识别SKU但原商品行未绑定内部ID时，沿同订单唯一来源SKU恢复历史金额和链接',()=>{
  const line={item_id:12,internal_sku_id:null,seller_sku:'legacy',quantity:1,historical_line_amount:'100',platform_product_id:'p1',platform_variant_id:'v1'};
  const s={counted:()=>true,c:{HTML2_SKU_ORDER_SALES:{orders:{'1|a':[line]}}}};
  const cost={...fact('a','product_cost','-5','2026-09-02'),cost_calculation:{components:[{sku_id:7,sku_code:'internal',source_sku:'legacy',quantity:1,net_cost:'5',currency:'PHP'}]}};
  const rows=itemMembers(s,[cost,fact('a','order_fee','-10','2026-09-02')]);
  expect(rows.map(x=>[x.sku_id,x.product_link_id])).toEqual([[7,'p1'],[7,'p1']]);expect(rows[1].amounts.order_fee).toBe(-10000000n);expect(rows[1].pending).toBe(false);
  line.internal_sku_id=99;expect(itemMembers(s,[cost,fact('a','order_fee','-10','2026-09-02')])[1].pending).toBe(true);
  line.internal_sku_id=null;s.c.HTML2_SKU_ORDER_SALES.orders['1|a'].push({...line,item_id:13,platform_variant_id:'v2'});expect(itemMembers(s,[cost,fact('a','order_fee','-10','2026-09-02')])[1].pending).toBe(true);
 });
 it('无订单公共费用只分给同店同币种同期有效结算订单，保留原日期及原流水证据',()=>{
  const fee={...fact('','order_fee','-40.000001','2026-09-11'),original_amount:'-999',source:'SaaS平台结算',rows:[{name:'Withholding Tax (LZD - Adj Debit)'}]};
  const sales=[fact('a','sales','100','2026-09-03'),fact('b','sales','100','2026-09-10'),fact('c','sales','300','2026-09-12'),{...fact('other','sales','10000','2026-09-10'),store_id:2}];
  const week=allocatePublicFees([fee],sales,'week');expect(week.map(f=>[f.external_order_id,f.amount])).toEqual([['b','-10.000000'],['c','-30.000001']]);
  expect(week.every(f=>f.period_date==='2026-09-11'&&f.date==='2026-09-11'&&f.allocation_readonly&&f.original_amount===f.amount)).toBe(true);expect(week[0].public_fee_evidence.fee_names).toContain('Withholding Tax (LZD - Adj Debit)');
  const half=allocatePublicFees([fee],sales,'half_month');expect(half.map(f=>f.external_order_id)).toEqual(['a','b','c']);
 });
 it('同一订单同一平台变体的重复商品行可归到同一SKU，不猜测不同变体或缺失历史价格',()=>{
  const lines=[{item_id:1,internal_sku_id:null,seller_sku:'A',platform_product_id:'p',platform_variant_id:'v',quantity:2,historical_line_amount:'347'},{item_id:2,internal_sku_id:null,seller_sku:'A',platform_product_id:'p',platform_variant_id:'v',quantity:1,historical_line_amount:'176'}];
  const s={counted:()=>true,c:{HTML2_SKU_ORDER_SALES:{orders:{'1|a':lines}}}},components=[{sku_id:7,source_sku:'A',quantity:2},{sku_id:7,source_sku:'A',quantity:1}];
  const cost={...fact('a','product_cost','0','2026-09-03'),cost_calculation:{components}};
  let rows=itemMembers(s,[fact('a','sales','523','2026-09-03')],[cost]);expect(rows.every(m=>m.sku_id===7&&m.product_link_id==='p'&&!m.pending)).toBe(true);expect(rows.reduce((n,m)=>n+m.amounts.sales,0n)).toBe(523000000n);
  lines[1].platform_variant_id='other';expect(itemMembers(s,[fact('a','sales','523','2026-09-03')],[cost])[0].pending).toBe(true);
  lines[1].platform_variant_id='v';lines[0].historical_line_amount=null;expect(itemMembers(s,[fact('a','sales','523','2026-09-03')],[cost])[0].pending).toBe(true);
 });
 it('公共费用没有同期分母、分母缺失或日期缺失时保留待分摊，冲正订单不承接费用',()=>{
  const fee=fact('','shop_adjustment','-10','2026-09-11'),sales=[fact('a','sales','100','2026-09-03')];
  expect(allocatePublicFees([fee],sales,'week')[0].external_order_id).toBe('');
  expect(allocatePublicFees([fee],[fact('a','sales','100','2026-09-10'),fact('b','sales',null,'2026-09-10')],'week')[0].external_order_id).toBe('');
  expect(allocatePublicFees([{...fee,period_date:null}],sales,'half_month')[0].period_date).toBeNull();
  const net=allocatePublicFees([fee],[fact('a','sales','100','2026-09-10'),fact('a','sales','-100','2026-09-11'),fact('b','sales','100','2026-09-10')],'week');expect(net.map(f=>f.external_order_id)).toEqual(['b']);
 });
 it('跨月自然周采用已载入的同期基数，保留来源账期；返还方向、币种和尾差不变',()=>{
  const fees=[fact('','order_fee','0.000003','2026-09-01')],sales=[fact('a','sales','100','2026-08-31'),fact('b','sales','200','2026-09-02'),{...fact('wrong-currency','sales','900','2026-09-02'),currency:'THB'}];
  const rows=allocatePublicFees(fees,sales,'week');expect(rows.map(f=>[f.external_order_id,f.amount])).toEqual([['a','0.000001'],['b','0.000002']]);expect(rows.every(f=>f.month==='2026-09'&&f.date==='2026-09-01')).toBe(true);
 });
 it('订单账本切粒度只重分公共订单费与店铺调整，月度、直接费用和仓库费用保持不变',()=>{
  const sales=[fact('a','sales','100','2026-09-03'),fact('b','sales','100','2026-09-10')],publicFee=fact('','order_fee','-20','2026-09-11'),adjustment=fact('','shop_adjustment','-10','2026-09-11'),direct=fact('a','order_fee','-3','2026-09-11'),warehouse=fact('a','warehouse_other','-5','2026-09-11'),parents=[...sales,publicFee,adjustment,direct,warehouse];
  const s={counted:f=>f.status!=='reference',p:{localFact:f=>f},c:{HTML2_STORE_HIERARCHY:{setMode:()=>{},stores:()=>[],controls:()=>parents,orderAllocation:rows=>rows.flatMap(f=>!f.external_order_id&&['order_fee','shop_adjustment'].includes(f.kind)?sales.map(r=>({...f,external_order_id:r.external_order_id,amount:String(Number(f.amount)/2),hierarchy_allocation:{method:'order_sales_share',source_ids:[f.source_id],order_sales:'100',store_sales:'200'}})):f)}}};
  const reclassification={...fact('','shop_adjustment','20','2026-09-01'),source_id:'hierarchy-reclassification:1'};parents.push(reclassification);
  s.c.TEST_SNAPSHOT={};const month=orderLedger(s,'month');expect(month.filter(f=>f.source_parent_id===publicFee.source_id).map(f=>f.amount)).toEqual(['-10.000000','-10.000000']);
  const week=orderLedger(s,'week');expect(week.filter(f=>f.public_fee_evidence).map(f=>[f.kind,f.external_order_id,f.amount])).toEqual([['order_fee','b','-20.000000'],['shop_adjustment','b','-10.000000']]);
  expect(week.find(f=>f.source_id===direct.source_id)).toEqual(month.find(f=>f.source_id===direct.source_id));expect(week.find(f=>f.source_id===warehouse.source_id)).toEqual(month.find(f=>f.source_id===warehouse.source_id));
  const offsets=rows=>rows.filter(f=>f.source_parent_id===reclassification.source_id).map(f=>[f.external_order_id,f.amount,f.period_date]);expect(offsets(week)).toEqual(offsets(month));
  expect(orderLedger(s,'half_month').filter(f=>f.public_fee_evidence).map(f=>f.external_order_id)).toEqual(['a','b','a','b']);
 });
 it('负数和微额尾差精确守恒，稳定分母，不用浮点金额',()=>{
  expect([...split(-5n,[['a',1n],['b',1n],['c',1n]]).values()].reduce((a,b)=>a+b,0n)).toBe(-5n);
  expect(split(-5n,[['a',1n],['b',1n],['c',1n]])).toEqual(new Map([['a',-2n],['b',-2n],['c',-1n]]));
 });
 it('同周实际广告只分给同周结算订单；半月允许不同结果',()=>{
  const sales=[fact('a','sales','100','2026-09-02'),fact('b','sales','300','2026-09-09')];
  const ads=[fact('','advertising','-40','2026-09-03'),fact('','advertising','-20','2026-09-10')];
  const week=allocateAdvertising(ads,sales,'week');
  expect(week.filter(f=>f.external_order_id==='a').map(f=>f.amount)).toEqual(['-40.000000']);
  expect(week.filter(f=>f.external_order_id==='b').map(f=>f.amount)).toEqual(['-20.000000']);
  const half=allocateAdvertising(ads,sales,'half_month');
  expect(half.find(f=>f.external_order_id==='a').amount).toBe('-15.000000');
  expect(half.find(f=>f.external_order_id==='b').amount).toBe('-45.000000');
 });
 it('无当期结算订单留待分摊，不转嫁；零额与待核不伪装成已确认',()=>{
  const rows=allocateAdvertising([fact('','advertising','-10','2026-09-20')],[fact('a','sales','10','2026-09-02')],'week');
  expect(rows[0].external_order_id).toBe('');expect(rows[0].amount).toBe('-10.000000');expect(rows[0].allocation_reason).toContain('结算');
 });
 it('销售冲正后无有效销售额的订单不承担当期广告；退款不直接改销售分母',()=>{
  const sales=[fact('a','sales','100','2026-09-02'),fact('a','sales','-100','2026-09-03'),fact('b','sales','100','2026-09-02'),fact('b','refund','-20','2026-09-03')];
  const rows=allocateAdvertising([fact('','advertising','-40','2026-09-03')],sales,'week');expect(rows).toHaveLength(1);expect(rows[0].external_order_id).toBe('b');expect(rows[0].amount).toBe('-40.000000');
 });
 it('同期销售分母有缺失时不把全额广告转嫁给已知部分订单',()=>{
  const rows=allocateAdvertising([fact('','advertising','-40','2026-09-03')],[fact('a','sales','100','2026-09-02'),fact('b','sales',null,'2026-09-02')],'week');
  expect(rows).toHaveLength(1);expect(rows[0].external_order_id).toBe('');expect(rows[0].amount).toBe('-40.000000');expect(rows[0].allocation_reason).toContain('分母不完整');
 });
 it('订单费用只在原订单内分摊；SKU和原链接金额来自相同商品份额',()=>{
  const fee=fact('a','order_fee','-10.000001','2026-09-03');
  const items=[{id:'a',sales_weight:1n,quantity_weight:9n},{id:'b',sales_weight:3n,quantity_weight:1n}];
  const rows=allocateItems(fee,items);
  expect(rows.map(r=>r.amount)).toEqual(['-2.500000','-7.500001']);
  expect(rows.every(r=>r.fact.external_order_id==='a')).toBe(true);
  expect(allocateItems({...fee,kind:'warehouse_order',amount:'-10'},items).map(r=>r.amount)).toEqual(['-9.000000','-1.000000']);
 });
 it('商品金额缺失不使用成本或数量猜测费用分配',()=>{
  const rows=allocateItems(fact('a','refund','-10','2026-09-03'),[{id:'a',sales_weight:null,quantity_weight:1n}]);
  expect(rows).toHaveLength(1);expect(rows[0].item).toBeNull();expect(rows[0].amount).toBe('-10.000000');
 });
 it('待归期广告不借用月初日期分摊给月初订单',()=>{
  const rows=allocateAdvertising([{...fact('','advertising','-10','2026-09-01'),period_date:null}],[fact('a','sales','100','2026-09-02')],'half_month');
  expect(rows[0].external_order_id).toBe('');expect(rows[0].period_date).toBeNull();expect(rows[0].amount).toBe('-10.000000');
 });
 it('广告费用池和订单份额的原额字段使用当前份额，不继承月度控制额或关账折算额',()=>{
  const ad={...fact('','advertising','-40','2026-09-03'),original_amount:'-36954.26',original_currency:'THB',locked_local_fact:{amount:'-36954.26',currency:'THB'}};
  const rows=allocateAdvertising([ad],[fact('a','sales','100','2026-09-02'),fact('b','sales','300','2026-09-03')],'week');
  expect(rows.map(r=>r.original_amount)).toEqual(['-10.000000','-30.000000']);expect(rows.every(r=>r.original_currency==='PHP'&&!r.locked_local_fact)).toBe(true);
  expect(rows[0].advertising_evidence[0].amount).toBe('-40');
  const pending=allocateAdvertising([{...ad,period_date:null}],[],'week')[0];expect(pending.original_amount).toBe('-40.000000');
 });
 it('订单内成本逐项归属，费用只用本订单商品价格；没有改成本版本',()=>{
  const components=[{sku_id:1,sku_code:'A',source_sku:'A',quantity:1,net_cost:'5',currency:'PHP',cost_version_no:3},{sku_id:2,sku_code:'B',source_sku:'B',quantity:1,net_cost:'20',currency:'PHP',cost_version_no:7}];
  const s={counted:f=>f.status!=='reference',c:{HTML2_SKU_ORDER_SALES:{orders:{'1|a':[{internal_sku_id:1,seller_sku:'A',quantity:1,historical_line_amount:'100',platform_product_id:'p1'},{internal_sku_id:2,seller_sku:'B',quantity:1,historical_line_amount:'300',platform_product_id:'p2'}]}}}};
  const cost={...fact('a','product_cost','-25','2026-09-02'),cost_calculation:{components}};
  const rows=itemMembers(s,[cost,fact('a','order_fee','-12','2026-09-02')]);
  expect(rows.filter(r=>r.fact.kind==='product_cost').map(r=>r.amounts.product_cost)).toEqual([-5000000n,-20000000n]);
  expect(rows.filter(r=>r.fact.kind==='order_fee').map(r=>r.amounts.order_fee)).toEqual([-3000000n,-9000000n]);
  expect(rows.filter(r=>r.component).map(r=>r.component.cost_version_no)).toEqual([3,7]);expect(rows.map(r=>r.product_link_id)).toEqual(['p1','p2','p1','p2']);
 });
 it('跨账期广告仍使用对应订单最终SKU及原成交链接，不回退到换货前SKU',()=>{
  const s={counted:()=>true,c:{HTML2_SKU_ORDER_SALES:{orders:{'1|a':[{internal_sku_id:1,seller_sku:'old',quantity:1,historical_line_amount:'100',platform_product_id:'original'}]},exchanges:{'1|a':{changes:[{action:'replace',old_sku_id:1,new_sku_id:2,reduce_quantity:1,add_quantity:1}]}}}}};
  const fee=fact('a','advertising','-10','2026-09-01'),cost={...fact('a','product_cost','-5','2026-08-31'),cost_calculation:{components:[{sku_id:2,sku_code:'new',quantity:1}]}};
  const rows=itemMembers(s,[fee],[fee,cost]);expect(rows[0].sku_id).toBe(2);expect(rows[0].product_link_id).toBe('original');expect(rows[0].amounts.advertising).toBe(-10000000n);
 });
 it('没有来源的科目为无已登记费用，明确缺金额的科目仍为缺失',()=>{
  const s={c:{SKU_SUMMARY:{group:members=>[{members}]}}};
  const g=groupMembers(s,[{amounts:{order_fee:null,sales:100n}}])[0];
  expect(g.amounts.order_fee).toEqual({amount:0n,known:0,missing:1});expect(g.amounts.promotion).toEqual({amount:0n,known:1,missing:0});
 });
 it('缺成本版本产生的占位零不冒充已确认零成本',()=>{
  const component={sku_id:1,sku_code:'A',quantity:1,unit_cost:null,net_cost:'0',currency:'PHP',reasons:['缺成本版本']};
  const s={counted:()=>true,c:{HTML2_SKU_ORDER_SALES:{orders:{'1|a':[{internal_sku_id:1,seller_sku:'A',quantity:1,historical_line_amount:'100',platform_product_id:'p1'}]}}}};
  const rows=itemMembers(s,[{...fact('a','product_cost','0','2026-09-02'),cost_calculation:{components:[component]}}]);
  expect(rows[0].amounts.product_cost).toBeNull();expect(rows[0].pending).toBe(true);
 });
 it('禁用月度广告后不留下周度原消耗；手工新增广告保留明确日期',()=>{
  const parent={...fact('','advertising','0','2026-09-01'),source_id:'hierarchy-ad:1',store_code:'test'};
  const report={operations:100n,spend:100n,details:[],actualDetails:[{date:'2026-09-02',amount:'-1'}],ledgerBase:{operations:0n},ledgerOriginal:{operations:-1000000n}};
  const s={p:{localFact:f=>f},c:{HTML2_STORE_HIERARCHY:{stores:()=>[]},HTML2_ADVERTISING_COLUMNS:{calculate:()=>report},LEDGER_FEES:{records:()=>({})}}};
  const disabled=dailyAdvertising(s,[parent],'operations');expect(disabled).toHaveLength(30);expect(disabled.every(r=>r.amount==='0.000000')).toBe(true);
  s.c.LEDGER_FEES.records=()=>({add:{id:'new:1',type:'new',state:'active',kind:'advertising',store:'1',month:'2026-09',mode:'operations',date:'2026-09-18',amount:'-10'}});
  const rows=dailyAdvertising(s,[{...parent,amount:'-10'}],'operations');expect(rows).toHaveLength(30);expect(rows.find(r=>r.period_date==='2026-09-18').amount).toBe('-10.000000');
 });
 it('日报与税额各计一次，财务充值口径不混入实际消耗，真正无日期差额仍待归期',()=>{
  const parent={...fact('','advertising','-3.07','2026-09-01'),source_id:'hierarchy-ad:1',store_code:'test'};
  const report={operations:307n,spend:300n,actualDetails:[{date:'2026-09-03',amount:'-1'},{date:'2026-09-18',amount:'-2'}],details:[{id:'charge:1',time:'2026-09-03T00:00:00',duration:86400000,tax:'0.07',debit:'1.07'}]};
  const s={p:{localFact:f=>f},c:{HTML2_STORE_HIERARCHY:{stores:()=>[]},HTML2_ADVERTISING_COLUMNS:{calculate:()=>report}}};
  const operations=dailyAdvertising(s,[parent],'operations');expect(operations.filter(r=>r.period_date==='2026-09-03')[0].amount).toBe('-1.070000');expect(operations.filter(r=>!r.period_date)).toEqual([]);
  expect(dailyAdvertising(s,[{...parent,amount:'-1.07'}],'finance').reduce((n,r)=>n+Number(r.amount),0)).toBeCloseTo(-1.07,6);
  const unknown=dailyAdvertising(s,[{...parent,amount:'-5.07'}],'operations').filter(r=>!r.period_date);expect(unknown.map(r=>r.amount)).toEqual(['-2.000000']);
 });
});
