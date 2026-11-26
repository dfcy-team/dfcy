import { describe,it,expect,vi } from 'vitest';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {calculate,scopedOptions,detail}=require('../../backend/apps/finance/summary_native.cjs');
const facts=[{source_id:'allowed',store_id:1,store_code:'A',country:'PH',date:'2026-09-01',currency:'PHP',amount:'100',kind:'sales',external_order_id:'same'}, {source_id:'forbidden',store_id:2,store_code:'B',country:'PH',date:'2026-09-01',currency:'PHP',amount:'900',kind:'sales',external_order_id:'same'}];
function session(){return {labels:{sales:'订单销售额'},c:{HTML2_STORE_HIERARCHY:{setMode(){}},LEDGER_FEES:{editable:()=>false}},p:{matches:()=>true,entriesFor:()=>facts,groupRows:rows=>rows.map(row=>({...row,cells:{}}))},ledgers:new Map([['month|operations',facts]]),queries:new Map(),options:{stores:[{id:'1',code:'A',country:'PH',currency:'PHP'},{id:'2',code:'B',country:'PH',currency:'PHP'}],countries:{PH:'菲律宾',TH:'泰国'},months:['2026-09'],closed_periods:[{shop:'A',month:'2026-09'},{shop:'B',month:'2026-09'}]}};}
describe('统一账本按授权店铺展示',()=>{
 it('在已完成分摊的账本上过滤，不重算已分摊金额',()=>{const s=session();expect(calculate(s,'store',{_stores:['1']},'operations')).toEqual([{...facts[0],cells:{},pending:false}]);expect(calculate(s,'store',{},'operations')).toEqual(facts.map(row=>({...row,cells:{},pending:false})));expect(s.ledgers.get('month|operations')).toEqual(facts);});
 it('原始流水与成本流水同样过滤，不能用相同订单号跨店读取',()=>{const s=session();s.rawFlows=facts;expect(calculate(s,'detail',{_stores:['1']},'operations')).toEqual([facts[0]]);s.rawFlows=null;s.costFlows=facts.map(f=>({...f,kind:'product_cost'}));expect(calculate(s,'detail',{_stores:['1']},'operations').every(f=>f.store_id===1)).toBe(true);});
 it('伪造其他店铺行键无法下钻，授权来源不返回完整原文件',()=>{const s=session();expect(()=>detail(s,{view:'detail',mode:'operations',filters:{_stores:['1']},row_key:'forbidden',kind:'sales'})).toThrow();s.ledgers.get('month|operations')[0]={...facts[0],source_proof:{private:'other-store-secret'}};const result=detail(s,{view:'detail',mode:'operations',filters:{_stores:['1']},row_key:'allowed',kind:'sales'});expect(result.html).toContain('授权店铺');expect(result.html).not.toContain('other-store-secret');});
 it('目录、币种和关账记录也限制在授权范围',()=>{const options=scopedOptions(session(),{_stores:['1']});expect(options.stores.map(s=>s.id)).toEqual(['1']);expect(Object.keys(options.countries)).toEqual(['PH']);expect(options.closed_periods).toEqual([{shop:'A',month:'2026-09'}]);expect(options.currencies).toEqual(['PHP']);});
});

it('筛选目录在当前批次按规范化权限范围复用，换范围或会话时重新生成',()=>{
 const s=session();s.p.entriesFor=vi.fn(()=>facts);
 const first=scopedOptions(s,{_stores:['2','1']});expect(scopedOptions(s,{_stores:['1','2','1'],month:'2026-10'})).toBe(first);expect(s.p.entriesFor).toHaveBeenCalledTimes(1);
 const limited=scopedOptions(s,{_stores:['1']});expect(limited.stores.map(shop=>shop.id)).toEqual(['1']);expect(s.p.entriesFor).toHaveBeenCalledTimes(2);expect(scopedOptions(session(),{_stores:['1']})).not.toBe(limited);
 for(let i=0;i<10;i++)scopedOptions(s,{_stores:[String(i)]});expect(s.scopedOptionCache.size).toBeLessThanOrEqual(8);
});

it('自然周按完整日期范围查询，跨月不被浏览月份截断且权限仍生效',()=>{
 const s=session(),rows=[{...facts[0],date:'2026-09-30',period_date:'2026-09-30'},{...facts[0],date:'2026-10-01',period_date:'2026-10-01'},{...facts[1],date:'2026-10-01',period_date:'2026-10-01'}];s.ledgers.set('week|operations',rows);s.ledgers.set('month|operations',rows);s.p.matches=(f,filters)=>!filters.month||f.date.startsWith(filters.month);
 const a=calculate(s,'store',{month:'2026-09',period_type:'week',period:'2026-09-28',_stores:['1']},'operations');const b=calculate(s,'store',{month:'2026-10',period_type:'week',period:'2026-09-28',_stores:['1']},'operations');expect(a).toEqual(b);expect(a.map(f=>f.date)).toEqual(['2026-09-30','2026-10-01']);expect(calculate(s,'store',{month:'2026-09',_stores:['1']},'operations')).toHaveLength(1);
});
