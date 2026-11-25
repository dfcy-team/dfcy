import { describe, expect, it } from 'vitest';
import { createRequire } from 'node:module';
const require=createRequire(import.meta.url);
const { summaryRatio, fieldIssues, summaryTotals }=require('../../backend/apps/finance/summary_native.cjs');
const s={rates:{displayAmount:value=>value,read:()=>({amount:0n,partial:false})},labels:{product_cost:'商品成本'}};

describe('平台账单独立字段计算与异常依据',()=>{
 it('跨页合计按全结果及币种计算，不混加当地币种',()=>{
  const groups=Array.from({length:21},(_,i)=>({key:String(i),currency:i===20?'MYR':'PHP',cells:{sales:{amount:1000000n,entries:[]},product_cost:{amount:-100000n,entries:[]}},balance:900000n}));
  const session={rates:{read:(g,k)=>({amount:g?.cells[k]?.amount??0n,partial:false}),profit:g=>g?.balance},p:{fixed:n=>n.toString()}};
  const map=new Map(groups.map(g=>[g.key,g]));
  expect(summaryTotals(session,groups,map,map,false)).toEqual([{currency:'PHP',sales:'20000000',operations:'18000000',finance:'18000000',partial:false},{currency:'MYR',sales:'1000000',operations:'900000',finance:'900000',partial:false}]);
 });
 it('零分母显示数字，负分母保留真实比值符号',()=>{
  expect(summaryRatio(s,-25000000n,0n)).toBe('0.00%');
  expect(summaryRatio(s,-25000000n,-100000000n)).toBe('25.00%');
  expect(summaryRatio(s,25000000n,-100000000n)).toBe('-25.00%');
  expect(summaryRatio(s,-25000000n,100000000n)).toBe('-25.00%');
 });
 it('缺失分母保留未知，不冒充零分母',()=>{
  expect(summaryRatio(s,1000000n,null)).toBe('—');
 });
 it('缺少金额依据时给出字段原因，不默认为零',()=>{
  expect(fieldIssues({...s,rates:{...s.rates,read:()=>({amount:null,partial:false})}},{cells:{}},'product_cost',false)[0]).toContain('尚不能认定为零');
 });
 it('字段异常保留原始原因，不污染无关费用',()=>{
  const group={cells:{product_cost:{entries:[{source_id:'cost:1',amount:null,description:'SKU A 未维护采购成本',cost_calculation:{state:'pending'}}]},order_fee:{entries:[{amount:'-10'}]}}};
  expect(fieldIssues(s,group,'product_cost',false)).toContain('SKU A 未维护采购成本');
  expect(fieldIssues(s,group,'order_fee',false)).toEqual([]);
 });
});
