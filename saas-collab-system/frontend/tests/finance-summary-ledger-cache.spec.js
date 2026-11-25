import {it,expect,vi} from 'vitest';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {orderLedger,itemMembers}=require('../../backend/apps/finance/summary_order_ledger.cjs');
const fact=(kind,amount,date,id)=>({store_id:1,store_code:'S1',platform:'shopee',external_order_id:'a',country:'PH',currency:'PHP',kind,amount,date,month:date.slice(0,7),source_id:id,status:'confirmed'});

it('共用月份索引仍按本账期首次结算归期，切换周维度不修改月结果或原记录',()=>{
 const sales=[fact('sales','100','2026-09-03','sale:sep'),fact('sales','100','2026-10-10','sale:oct')];
 const fees=[fact('order_fee','-10','2026-09-15','hierarchy-fee:sep'),fact('order_fee','-20','2026-10-15','hierarchy-fee:oct')].map(f=>({...f,external_order_id:''}));
 const parents=[...sales,...fees],original=JSON.stringify(parents);
 const generated=fees.map(f=>({...f,external_order_id:'a',hierarchy_allocation:{method:'order_sales_share',source_ids:[f.source_id],order_sales:'100'}}));
 const s={counted:()=>true,p:{localFact:f=>f},c:{HTML2_STORE_HIERARCHY:{setMode(){},stores:()=>[],controls:()=>parents,orderAllocation:()=>[...sales,...generated]}}};
 const month=orderLedger(s,'month'),saved=JSON.stringify(month);
 expect(month.filter(f=>f.kind==='order_fee').map(f=>f.period_date)).toEqual(['2026-09-03','2026-10-10']);
 orderLedger(s,'week');expect(JSON.stringify(month)).toBe(saved);
 expect(orderLedger(s,'month')).toEqual(month);expect(JSON.stringify(parents)).toBe(original);
});

it('同组来源复用权重，微额正负数仍分别守恒并保留各自来源',()=>{
 const sales=[{...fact('sales','100','2026-09-03','sale:a'),external_order_id:'a'},{...fact('sales','200','2026-09-03','sale:b'),external_order_id:'b'}];
 const fees=[fact('order_fee','-0.000001','2026-09-03','fee:a'),fact('order_fee','0.000002','2026-09-03','fee:b')].map(f=>({...f,external_order_id:''}));
 const readers=[vi.fn(()=> '100'),vi.fn(()=> '200')];
 const allocated=sales.map((f,i)=>{const info={method:'order_sales_share',source_ids:fees.map(f=>f.source_id)};Object.defineProperty(info,'order_sales',{enumerable:true,get:readers[i]});return{...f,kind:'order_fee',hierarchy_allocation:info};});
 const parents=[...sales,...fees],s={counted:()=>true,p:{localFact:f=>f},c:{HTML2_STORE_HIERARCHY:{setMode(){},stores:()=>[],controls:()=>parents,orderAllocation:()=>[...sales,...allocated]}}};
 const rows=orderLedger(s).filter(f=>f.kind==='order_fee');
 expect(rows.filter(f=>f.source_parent_id==='fee:a').map(f=>f.amount)).toEqual(['0.000000','-0.000001']);
 expect(rows.filter(f=>f.source_parent_id==='fee:b').map(f=>f.amount)).toEqual(['0.000001','0.000001']);
 for(const read of readers)expect(read).toHaveBeenCalledTimes(3);
 expect(fees.map(f=>f.amount)).toEqual(['-0.000001','0.000002']);
});

it('同一不可变会话复用商品匹配和成本索引，费用金额与不同成本依据独立处理',()=>{
 const amount=vi.fn(()=> '100'),kind=vi.fn(()=> 'product_cost');
 const line={internal_sku_id:7,seller_sku:'sku',quantity:1,platform_product_id:'p1'};
 Object.defineProperty(line,'historical_line_amount',{get:amount});
 const component={sku_id:7,sku_code:'sku',source_sku:'sku',quantity:1};
 const cost={...fact('product_cost','-1','2026-09-03','cost'),cost_calculation:{components:[component]}};
 Object.defineProperty(cost,'kind',{get:kind});
 const full=[cost],fee=fact('order_fee','-10','2026-09-03','fee');
 const s={counted:()=>true,c:{HTML2_SKU_ORDER_SALES:{orders:{'1|a':[line]}}},itemMatches:new Map(),itemCostIndexes:new WeakMap()};
 const first=itemMembers(s,[fee],full),amountReads=amount.mock.calls.length,kindReads=kind.mock.calls.length;
 expect(first[0].amounts.order_fee).toBe(-10000000n);expect(first[0].pending).toBe(false);
 expect(itemMembers(s,[{...fee,amount:'-20'}],full)[0].amounts.order_fee).toBe(-20000000n);
 expect(amount.mock.calls.length).toBe(amountReads);expect(kind.mock.calls.length).toBe(kindReads);
 const changed={...cost,cost_calculation:{components:[{...component,sku_id:88}]}};
 expect(itemMembers(s,[fee],[changed])[0].pending).toBe(true);
 expect(first[0].amounts.order_fee).toBe(-10000000n);
});
