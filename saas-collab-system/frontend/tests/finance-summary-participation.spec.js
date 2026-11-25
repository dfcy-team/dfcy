import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import vm from 'node:vm';
const code=fs.readFileSync('../backend/apps/finance/summary_participation.js','utf8');
function fixture({closed=false,duplicate=false}={}){
 const raw=[{source_id:'finance-transaction:1',store_id:5,store_code:'LZ5',date:'2026-10-03',currency:'PHP',kind:'order_fee',amount:'-12.00',status:'confirmed'},
 {source_id:'finance-transaction:2',store_id:5,store_code:'LZ5',date:'2026-10-03',currency:'PHP',kind:'order_fee',amount:'-8.00',status:'confirmed'}];
 const fact={source_id:'group:1',store_id:5,store_code:'LZ5',date:'2026-10-03',currency:'PHP',kind:'order_fee',amount:'-20.00',rows:[{id:1,amount:'-12.00',currency:'PHP'},{id:2,amount:'-8.00',currency:'PHP'}]};
 const values=new Map(),context={TEST_SNAPSHOT:{database:{raw_flows:raw,facts:duplicate?[fact,{...fact,source_id:'group:2'}]:[fact]}},micro:n=>BigInt(Math.round(Number(n)*100)),fixed:n=>(Number(n)/100).toFixed(2),localStorage:{getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)},HTML2_PROFIT_RULES:{closedFor:()=>closed}};
 vm.createContext(context);vm.runInContext(code,context);return{api:context.RAW_PARTICIPATION,values,raw,fact};
}
describe('原始流水参与控制',()=>{
 it('规则控制的记录明确说明限制，不误报为缺少唯一映射',()=>{
  const {api,raw,fact}=fixture();raw[0].kind='advertising';fact.kind='advertising';expect(api.info(raw[0].source_id).reason).toContain('广告或成本分摊规则');
 });
 it('仅排除所选流水，组内其他费用保持，原始证据不被改写，恢复无尾差',()=>{
  const {api,values,fact,raw}=fixture();const source=JSON.stringify({fact,raw});
  values.set(api.key,JSON.stringify(api.prepare({id:raw[0].source_id,operation:'exclude_source',reason:'重复导入'})));
  expect(api.apply([fact])[0].amount).toBe('-8.00');expect(api.apply([fact])[0].rows.map(r=>r.id)).toEqual([2]);
  expect(JSON.stringify({fact,raw})).toBe(source);expect(api.info(raw[0].source_id).excluded).toBe(true);
  values.set(api.key,JSON.stringify(api.prepare({id:raw[0].source_id,operation:'restore_source',reason:'已核对为有效流水'})));
  expect(api.apply([fact])[0].amount).toBe('-20.00');expect(api.state().history).toHaveLength(2);
 });
 it('拒绝未知来源、多个核算映射及已关账店铺',()=>{
  expect(()=>fixture().api.prepare({id:'foreign:1',operation:'exclude_source',reason:'测试'})).toThrow('未找到');
  expect(fixture({duplicate:true}).api.info('finance-transaction:1').supported).toBe(false);
  expect(()=>fixture({closed:true}).api.prepare({id:'finance-transaction:1',operation:'exclude_source',reason:'测试'})).toThrow('已关账');
 });
 it('要求原因、拒绝重复操作和客户端伪造金额',()=>{
  const {api,values}=fixture(),record={id:'finance-transaction:1',operation:'exclude_source',reason:'核对'};
  expect(()=>api.prepare({...record,reason:''})).toThrow('原因');expect(()=>api.prepare({...record,amount:'0.00'})).toThrow('无效');
  values.set(api.key,JSON.stringify(api.prepare(record)));expect(()=>api.prepare(record)).toThrow('未改变');
 });
 it('来源金额变化时停止应用旧排除，避免重建后静默挂错记录',()=>{
  const {api,values,raw,fact}=fixture();values.set(api.key,JSON.stringify(api.prepare({id:raw[0].source_id,operation:'exclude_source',reason:'核对'})));
  raw[0].amount='-99.00';expect(()=>api.apply([fact])).toThrow('已变化');
 });
});
