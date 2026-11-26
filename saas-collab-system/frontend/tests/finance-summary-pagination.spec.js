import {it,expect,vi} from 'vitest';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {table,calculate,query}=require('../../backend/apps/finance/summary_native.cjs');
const {micro,fixed}=require('../../backend/apps/finance/summary_allocation.cjs');

function session(){
 const facts=[1,2].map(id=>({source_id:'sale:'+id,store_id:id,store_code:'S'+id,country:'PH',external_order_id:'order'+id,kind:'sales',amount:String(id*100),currency:'PHP',date:'2026-09-01',month:'2026-09'}));
 return {countries:{PH:'菲律宾'},labels:{sales:'销售额'},counted:()=>true,
  c:{HTML2_STORE_HIERARCHY:{setMode(){}},LEDGER_FEES:{editable:()=>false}},
  p:{micro,fixed,localFact:f=>f,matches:(f,filters)=>!filters.month||f.month===filters.month,entriesFor:()=>facts,
   groupRows:rows=>rows.map(f=>({...f,cells:{sales:{amount:micro(f.amount),entries:[f]}}}))},
  rates:{fields:[],displayAmount:n=>n,read:vi.fn((g,k)=>({amount:g?.cells[k]?.amount??0n,partial:false})),profit:g=>g?.cells.sales.amount??0n},
  ledgers:new Map([['month|operations',facts],['month|finance',facts]]),queries:new Map(),
  options:{stores:facts.map(f=>({id:String(f.store_id),code:f.store_code,country:'PH',currency:'PHP'})),countries:{PH:'菲律宾'},months:['2026-09'],closed_periods:[]}};
}

it('翻页复用全结果统计，切换授权范围与账期后不会复用其他结果',()=>{
 const s=session(),input={view:'store',filters:{month:'2026-09'},page:1,page_size:1};
 const first=table(s,input),firstCalls=s.rates.read.mock.calls.length;
 s.rates.read.mockClear();
 const second=table(s,{...input,page:2});
 expect(second.summary_totals).toBe(first.summary_totals);
 expect(second.attribution).toBe(first.attribution);
 expect(second.rows[0].identity.shop).toBe('S2');
 expect(s.rates.read.mock.calls.length).toBeLessThan(firstCalls);
 const scoped=table(s,{...input,filters:{month:'2026-09',_stores:['1']}});
 expect(scoped.total).toBe(1);expect(scoped.summary_totals[0].sales).toBe('100.000000');
 expect(first.summary_totals[0].sales).toBe('300.000000');
 expect(scoped.options.stores.map(x=>x.id)).toEqual(['1']);
 expect(table(s,{...input,filters:{month:'2026-10'}}).total).toBe(0);
 const fresh=table(session(),input);
 expect(fresh.summary_totals).toEqual(first.summary_totals);expect(fresh.summary_totals).not.toBe(first.summary_totals);
});

it('同一查询复用双口径，新条件淘汰旧大表而账本继续复用',()=>{
 const s=session(),filters={month:'2026-09'},a=query(s,'store',filters,'operations'),b=query(s,'store',filters,'finance');
 expect(query(s,'store',filters,'operations')).toBe(a);expect(query(s,'store',filters,'finance')).toBe(b);
 expect(s.queries.size).toBe(2);
 query(s,'store',{month:'2026-10'},'operations');
 expect([...s.queries.values()]).not.toContain(a);expect([...s.queries.values()]).not.toContain(b);
 calculate(s,'store',filters,'operations');expect([...s.ledgers.keys()]).toEqual(['month|finance','month|operations']);
});

it('流水分页不为未请求页读取行键，仍保留全量统计和页数',()=>{
 const s=session(),filters={month:'2026-09'},rows=Array.from({length:41},(_,i)=>({source_id:'flow:'+i,store_id:1,store_code:'S1',external_order_id:'o'+i,kind:'sales',currency:'PHP',amount:'100',date:'2026-09-01'}));
 const lastKey=vi.fn(()=> 'flow:40');Object.defineProperty(rows[40],'source_id',{get:lastKey,enumerable:true});
 const key=JSON.stringify(['detail',filters,'operations','store']),totals=[{currency:'PHP',sales:'4100.000000'}];
 s.queryGroup=JSON.stringify(['detail',filters,'store']);s.queries.set(key,rows);s.tableStats=new Map([[key,{summary_totals:totals,attribution:{totals:[],item_gaps:[],pending_rows:0},undated:0}]]);
 const first=table(s,{view:'detail',filters,page:1,page_size:20}),second=table(s,{view:'detail',filters,page:2,page_size:20});
 expect(first.rows).toHaveLength(20);expect(second.rows).toHaveLength(20);expect(second.rows[0].key).toBe('flow:20');
 expect(second.total).toBe(41);expect(second.page).toBe(2);expect(second.summary_totals).toBe(totals);expect(lastKey).not.toHaveBeenCalled();
 const last=table(s,{view:'detail',filters,page:3,page_size:20});expect(last.rows).toHaveLength(1);expect(last.rows[0].key).toBe('flow:40');
});

it('构成来源每页50笔，保留全量构成、金额、总数及稳定来源键',()=>{
 const {detail}=require('../../backend/apps/finance/summary_native.cjs'),s=session(),filters={month:'2026-09'};
 const entries=Array.from({length:101},(_,i)=>({source_id:'source:'+i,store_id:1,store_code:'S1',external_order_id:'order:'+i,kind:'sales',amount:'1',currency:'PHP',date:'2026-09-01'}));
 const group={key:'shop',currency:'PHP',cells:{sales:{amount:micro('101'),entries}}};
 s.queryGroup=JSON.stringify(['store',filters,'store']);s.queries.set(JSON.stringify(['store',filters,'operations','store']),[group]);
 s.c.FINANCE_COMPOSITION={fromEntries:(_,amount)=>[{label:'销售入账',amount,leaf:true,included:true}]};
 const input={view:'store',filters,mode:'operations',row_key:'shop',kind:'sales'};
 const legacy=detail(s,input),pages=[1,2,3].map(flow_page=>detail(s,{...input,flow_page}));
 expect(pages.map(p=>p.records.length)).toEqual([50,50,1]);
 expect(pages.flatMap(p=>p.records.map(r=>r.key))).toEqual(legacy.records.map(r=>r.key));
 for(const page of pages){expect(page.records_total).toBe(101);expect(page.parts).toEqual(legacy.parts);expect(page.amount).toBe(legacy.amount);}
});
