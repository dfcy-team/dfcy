import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import CostDetail from '../src/views/finance/FinanceCostDetail.vue';
const require=createRequire(import.meta.url),{costDetail}=require(path.resolve('../backend/apps/finance/summary_cost_detail.cjs'));
const micro=value=>{const s=String(value),[whole,fraction='']=s.replace(/^-/,'').split('.');return (BigInt(whole)*1000000n+BigInt(fraction.padEnd(6,'0')))*(s.startsWith('-')?-1n:1n);};
const fixed=n=>{const a=n<0n?-n:n;return(n<0n?'-':'')+(a/1000000n)+'.'+String(a%1000000n).padStart(6,'0');};
const display=n=>n==null?null:(n<0n?-1n:1n)*(((n<0n?-n:n)+5000n)/10000n)*10000n;
function facts(count=5){
 return Array.from({length:count},(_,i)=>({source_id:'cost:'+i,store_id:51,store_code:'LZ10PH',
  external_order_id:'order'+i,date:'2026-09-'+String(i+1).padStart(2,'0'),kind:'product_cost',currency:'PHP',amount:'-239.8005',status:'confirmed',
  cost_conversion:{period:'2026-09',from:'CNY',to:'PHP',quote:{input_id:40,rate:'9.55',source:'已确认业务汇率'}},
  cost_calculation:{state:'calculated',cost_at:'2026-09-'+String(i+1).padStart(2,'0'),reasons:[],components:[
   {sku_id:1,sku_code:'101010005-pink-150X200CM',quantity:1,unit_cost:'25.110000',currency:'CNY',net_cost:'25.110000',
    local_amount:'-239.800500',cost_version_id:11266,cost_version_no:3,cost_effective_from:'2026-08-01',reasons:[]}]}}));
}
function build(entries,level='items',page=1,classify){
 const c={HTML2_FEE_RATES:{displayAmount:display},micro,fixed};vm.createContext(c);
 vm.runInContext(fs.readFileSync(path.resolve('../backend/apps/finance/summary_composition.js'),'utf8'),c);
 const target=entries.reduce((n,f)=>n+(f.amount==null?0n:micro(f.amount)),0n),parts=c.FINANCE_COMPOSITION.fromEntries(entries,target);
 return {parts,result:costDetail({p:{micro,fixed},c:{HTML2_COST_COMPOSITION:{classify}}},{entries,parts,target,partial:false,sales:null,input:{cost_page:page},level})};
}
describe('成本分层构成',()=>{
 it('五笔同版本商品累计5件和125.55原币成本，日期与来源不重复堆叠',()=>{
  const {parts,result}=build(facts()),item=result.cost.rows[0];
  expect(item.quantity).toBe(5);expect(item.original_amount).toBe('125.550000');
  expect(item.unit_cost).toBe('25.110000');expect(item.amount).toBe('-1199.000000');
  expect(parts[1].label).toContain('× 5');expect(parts[1].source).toContain('125.550000');
  expect(parts[0].source.length).toBeLessThan(180);
  expect(result.cost.quotes).toHaveLength(1);expect(result.cost.date_from).toBe('2026-09-01');expect(result.cost.date_to).toBe('2026-09-05');
 });
 it('一个缺失项不隐藏已知合计，未知原币成本仍为null',()=>{
  const entries=facts(2);entries[1].amount=null;entries[1].status='pending';
  const c=entries[1].cost_calculation;c.state='pending';c.reasons=['SKU待关联'];
  c.components=[{...c.components[0],sku_id:2,cost_version_id:null,unit_cost:null,net_cost:'0',local_amount:null,reasons:['缺成本']}];
  const {result}=build(entries);
  expect(result.cost.known_amount).toBe('-239.800500');expect(result.cost.partial).toBe(true);
  expect(result.cost.pending_orders).toBe(1);expect(result.cost.missing_items).toBe(1);
  expect(result.cost.rows.find(r=>r.version_id===null).original_amount).toBeNull();
 });
 it('店铺订单列表每页20笔，分页不改变总体成本和待核数量',()=>{
  const entries=facts(21),a=build(entries,'orders',1).result.cost,b=build(entries,'orders',2).result.cost;
  expect(a.rows).toHaveLength(20);expect(b.rows).toHaveLength(1);
  expect(a.known_amount).toBe(b.known_amount);expect(a.order_count).toBe(21);
  expect(a.total).toBe(21);expect(b.page).toBe(2);
  expect(JSON.stringify(a).length).toBeLessThan(16000);
 });
 it('已知原币成本缺少折算额时，明示汇率待核而不补零',()=>{
  const entries=facts(1);entries[0].amount=null;entries[0].cost_calculation.components[0].local_amount=null;
  const item=build(entries).result.cost.rows[0];
  expect(item.amount).toBeNull();expect(item.original_amount).toBe('25.110000');
  expect(item.reasons).toContain('缺少折算汇率或已确认折算金额');
 });
 it('组件默认折叠来源，展示累计值并发出订单下钻和分页事件',async()=>{
  const cost=build(facts(21),'orders',1).result.cost;
  const w=mount(CostDetail,{props:{cost,money:v=>v==null?'—':Number(v).toFixed(2)}});
  expect(w.find('.cost-basis').attributes('open')).toBeUndefined();
  expect(w.findAll('.cost-scroll tbody tr')).toHaveLength(20);
  await w.find('.cost-scroll tbody .link').trigger('click');expect(w.emitted('drill')[0]).toEqual(['cost:0']);
  await w.findAll('.cost-pages button')[1].trigger('click');expect(w.emitted('page')[0]).toEqual([2]);
  w.unmount();
 });
 it('分类依据缺失单独待核，已知成本不伪装成正常订单',()=>{
  const cost=build(facts(),'orders').result.cost;
  expect(cost.classification_pending).toBe(5);expect(cost.pending_orders).toBe(0);
  expect(cost.categories.find(r=>r.key==='normal:cost').amount).toBeNull();
  expect(cost.categories.find(r=>r.key==='pending:cost').amount).toBe(cost.known_amount);
  expect(cost.categories.reduce((n,r)=>n+(r.amount==null?0n:micro(r.amount)),0n)).toBe(micro(cost.known_amount));
 });
 it('跨月回冲保留原成本日期、实际归属日及入库关联，不因退款自行回冲',()=>{
  const original=facts(1)[0],credit={...original,source_id:'return:receipt-1',date:'2026-10-03',amount:'239.8005',
   cost_event:'return',original_cost_date:'2026-09-01',original_cost_id:original.source_id,
   return_event:{id:'receipt-1',verified:true,confirmed_at:'2026-10-03'},cost_calculation:{state:'calculated',components:[]}};
  const cost=build([original,credit],'orders',1,()=> 'refund').result.cost;
  expect(cost.categories.find(r=>r.key==='refund:cost').amount).toBe('-239.800500');
  expect(cost.categories.find(r=>r.key==='refund:return').amount).toBe('239.800500');
  expect(cost.category_total).toBe('0.000000');expect(cost.classification_pending).toBe(0);
  expect(cost.cross_month_returns).toEqual({count:1,amount:'239.800500'});
  expect(cost.rows[1]).toMatchObject({original_date:'2026-09-01',accounting_date:'2026-10-03',cross_month:true,pending:false});
  expect(cost.rows[1].relation).toContain('receipt-1');
  const noCredit=build([original],'orders',1,()=> 'refund').result.cost;
  expect(noCredit.categories.find(r=>r.key==='refund:return').amount).toBeNull();
  expect(noCredit.cross_month_returns.count).toBe(0);
 });
 it('已有回冲缺入库依据及原日期保持待核，SKU流水键不重复',()=>{
  const credit={...facts(1)[0],cost_event:'return',amount:'10',date:'2026-10-03',cost_detail_key:'component:1',cost_calculation:{components:[]}};
  const cost=build([credit,{...credit,cost_detail_key:'component:2'}]).result.cost;
  expect(cost.flows.rows.map(r=>r.key)).toEqual(['component:1','component:2']);
  expect(cost.flows.rows[0].original_date).toBeNull();expect(cost.flows.rows[0].pending).toBe(true);
  expect(cost.cross_month_returns.count).toBe(0);
 });
});
