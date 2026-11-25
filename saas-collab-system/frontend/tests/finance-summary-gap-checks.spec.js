import {it,expect} from 'vitest';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {itemAttribution,itemMembers}=require('../../backend/apps/finance/summary_order_ledger.cjs');
const line=(id=7,price='100',product='p1')=>({internal_sku_id:id,seller_sku:'sku'+id,quantity:1,historical_line_amount:price,platform_product_id:product});
const fact=(kind='order_fee',amount='-10')=>({store_id:1,store_code:'S1',external_order_id:'a',currency:'PHP',country:'PH',platform:'shopee',date:'2026-09-01',kind,amount,source_id:'synthetic'});
const s=lines=>({counted:f=>f.status!=='reference',c:{HTML2_SKU_ORDER_SALES:{orders:{'1|a':lines}}},itemMatches:new Map(),itemCostIndexes:new WeakMap()});
function fullReport(session,rows){
 const groups=new Map();
 for(const m of itemMembers(session,rows)){
  if(!m.fact.external_order_id||Object.values(m.amounts).every(n=>n===0n)||m.sku_id&&m.product_link_id)continue;
  if(!groups.has(m.shop))groups.set(m.shop,{orders:new Set(),sku_orders:new Set(),link_orders:new Set()});
  const g=groups.get(m.shop);g.orders.add(m.fact.external_order_id);if(!m.sku_id)g.sku_orders.add(m.fact.external_order_id);if(!m.product_link_id)g.link_orders.add(m.fact.external_order_id);
 }
 return [...groups].map(([store,g])=>({store,orders:g.orders.size,sku_orders:g.sku_orders.size,link_orders:g.link_orders.size}));
}
it.each([
 ['完整商品', [line()],fact(),0],
 ['完整商品未知金额', [line()],fact('refund',null),0],
 ['未知销售权重', [line(7,null)],fact(),1],
 ['仓库费用按已知数量', [line(7,null)],fact('warehouse_order'),0],
 ['零金额且缺商品', [],fact('order_fee','0'),0],
 ['无商品的未知金额', [],fact('order_fee',null),1],
 ['微额只分到完整商品', [line(7,'1000'),line(null,'1','')],fact('order_fee','-0.000001'),0],
 ['微额分到缺失商品', [line(7,'1'),line(null,'1000','')],fact('order_fee','-0.000001'),1],
 ['数量分摊零份额不报缺项', [line(7,'1'),line(null,'1000','')],fact('warehouse_order','-0.000001'),0],
 ['无订单费用', [],{...fact(),external_order_id:''},0],
 ['仅核对记录', [],{...fact(),status:'reference'},0],
 ['成本尾差', [line()],{...fact('product_cost','-6'),cost_calculation:{components:[{sku_id:7,source_sku:'sku7',quantity:1,net_cost:'5',currency:'PHP'}]}},1],
 ['零额成本有非零分项与尾差', [line()],{...fact('product_cost','0'),cost_calculation:{components:[{sku_id:7,source_sku:'sku7',quantity:1,net_cost:'5',currency:'PHP'}]}},1],
])('快速归属检查与完整分摊一致：%s',(_,lines,row,count)=>{
 const session=s(lines),rows=[row],report=itemAttribution(session,rows,rows);
 expect(report).toHaveLength(count);expect(report).toEqual(fullReport(session,rows));
});
