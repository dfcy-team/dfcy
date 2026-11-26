import {it,expect,vi} from 'vitest';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {query}=require('../../backend/apps/finance/summary_native.cjs');

it('只保留当前查询的双口径结果，切换条件前释放旧大表且重复分页复用',()=>{
 const facts=[{store_id:1,source_id:'synthetic',amount:'10',currency:'PHP',kind:'sales'}];
 const s={c:{HTML2_STORE_HIERARCHY:{setMode(){}}},queries:new Map(),
  ledgers:new Map([['month|operations',facts],['month|finance',facts]]),
  p:{matches:()=>true,groupRows:vi.fn(rows=>rows.map(row=>({...row,cells:{}})))}};
 const filters={month:'2026-10'},first=query(s,'store',filters,'operations');
 query(s,'store',filters,'finance');
 expect(query(s,'store',filters,'operations')).toBe(first);
 expect(s.p.groupRows).toHaveBeenCalledTimes(2);
 const compute=s.p.groupRows.getMockImplementation();
 s.p.groupRows.mockImplementation(rows=>{expect(s.queries.size).toBeLessThan(2);return compute(rows);});
 for(let index=0;index<20;index++){
  const changed={...filters,order:String(index)};
  expect(query(s,'store',changed,'operations')).toEqual(first);
  expect([...s.queries.values()]).not.toContain(first);
  query(s,'store',changed,'finance');
  expect(s.queries.size).toBe(2);
 }
 s.p.groupRows.mockImplementation(()=>{expect(s.queries.size).toBe(0);throw Error('synthetic failure');});
 expect(()=>query(s,'order',filters,'operations')).toThrow('synthetic failure');
 expect(s.queries.size).toBe(0);
});
