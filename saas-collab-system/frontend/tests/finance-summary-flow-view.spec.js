import { describe, expect, it,vi } from 'vitest';
import { createRequire } from 'node:module';
const require=createRequire(import.meta.url);
const {flowAmounts,flowInclusion,flowState,flowStatus,flowEditBlock}=require('../../backend/apps/finance/summary_flow_view.cjs');
const {calculate}=require('../../backend/apps/finance/summary_native.cjs');

it('未启用关键词或编辑筛选时不构建搜索文本和编辑状态，筛选结果保持一致',()=>{
 const description=vi.fn(()=> '退款 REFERENCE'),editable=vi.fn(()=>true);
 const fact={source_id:'fee:1',kind:'order_fee',store_id:1,external_order_id:'one',ledger_key:'fee1',amount:'-10',date:'2026-09-01'};
 Object.defineProperty(fact,'description',{get:description});
 const s={c:{HTML2_STORE_HIERARCHY:{setMode(){}},LEDGER_FEES:{editable}},p:{matches:()=>true},ledgers:new Map([['month|operations',[fact]]])};
 expect(calculate(s,'detail',{},'operations')).toEqual([fact]);expect(description).not.toHaveBeenCalled();expect(editable).not.toHaveBeenCalled();
 expect(calculate(s,'detail',{keyword:'reference'},'operations')).toEqual([fact]);expect(description).toHaveBeenCalledTimes(1);
 expect(calculate(s,'detail',{editable:true},'operations')).toEqual([fact]);expect(editable).toHaveBeenCalledTimes(1);
 expect(calculate(s,'detail',{status:'readonly'},'operations')).toEqual([]);
 expect(calculate(s,'detail',{status:'pending'},'operations')).toEqual([]);
 expect(calculate(s,'detail',{from:'2026-09-02'},'operations')).toEqual([]);
});

it('原始流水分支跳过会被覆盖的账本和成本筛选，仍限制店铺、原币、日期及人工记录',()=>{
 const fact=(source_id,extra={})=>({source_id,store_id:1,external_order_id:'order',kind:'order_fee',currency:'PHP',original_currency:'USD',amount:'-1',date:'2026-09-10',...extra});
 const raw=fact('raw'),manual=fact('manual',{ledger_added:true,date:'2026-09-01'});
 const matches=vi.fn(f=>{if(['ledger','cost'].includes(f.source_id))throw Error('discarded branch traversed');return true;});
 const s={c:{HTML2_STORE_HIERARCHY:{setMode(){}}},p:{matches,entriesFor:()=>[manual,fact('not-manual')],localFact:f=>f},
  ledgers:new Map([['month|operations',[fact('ledger')]]]),costFlows:[fact('cost')],rawFlows:[raw,fact('forbidden',{store_id:2}),fact('other-currency',{original_currency:'MYR'}),fact('old',{date:'2026-08-01'})]};
 expect(calculate(s,'detail',{_stores:['1'],currency:'USD',from:'2026-09-01',to:'2026-09-30'},'operations')).toEqual([raw,manual]);
 expect(matches.mock.calls.some(([f])=>['ledger','cost','forbidden','other-currency'].includes(f.source_id))).toBe(false);
 s.rawFlows=[];expect(calculate(s,'detail',{},'operations')).toEqual([manual]);
});

it('待归属明细仍查账本，旧批次没有原始流水时仍合并成本',()=>{
 const ledger={source_id:'ledger',store_id:1,external_order_id:'',kind:'order_fee',amount:'-1',date:'2026-09-10'},cost={...ledger,source_id:'cost',kind:'product_cost',external_order_id:'known'};
 const s={c:{HTML2_STORE_HIERARCHY:{setMode(){}}},p:{matches:()=>true,micro:value=>BigInt(value),entriesFor:()=>[],localFact:f=>f},ledgers:new Map([['month|operations',[ledger]]]),costFlows:[cost],rawFlows:[]};
 expect(calculate(s,'detail',{attribution:'pending'},'operations')).toEqual([ledger]);
 delete s.rawFlows;s.ledgers.set('month|operations',[{...ledger,external_order_id:'known'}]);
 expect(calculate(s,'detail',{},'operations').map(f=>f.source_id)).toEqual(['ledger','cost']);
});

describe('原始流水折算与实际计入口径',()=>{
 it('原额保持原币，折算金额和依据来自既有核算函数',()=>{
  const fact={currency:'USD',amount:'-10.00',date:'2026-10-03'};
  const s={p:{localFact:f=>({...f,currency:'PHP',amount:'-585.00',fx:{rate:'58.5',basis:'日汇率',input_id:7}})}};
  expect(flowAmounts(s,fact)).toMatchObject({original_amount:'-10.00',original_currency:'USD',amount:'-585.00',currency:'PHP',conversion:{rate:'58.5',input_id:7,missing:false}});
  expect(fact).toEqual({currency:'USD',amount:'-10.00',date:'2026-10-03'});
 });
 it('缺汇率保留待核，未知原额不回退成零或其他金额',()=>{
  const s={p:{localFact:f=>({...f,currency:'PHP',amount:null})}};
  expect(flowAmounts(s,{currency:'USD',amount:'10.00',date:'2026-10-03'}).conversion.missing).toBe(true);
  expect(flowAmounts(s,{currency:'USD',amount:'10.00',original_amount:null,date:'2026-10-03'}).original_amount).toBeNull();
 });
 function runtime(){
  const a={source_id:'finance-transaction:1',store_id:5},b={source_id:'ad:1',store_id:5};let mode='operations';
  const base={source_id:'fee-group',store_id:5,external_order_id:'O1',amount:'-10',period_date:'2026-10-03',rows:[{id:1}]};
  const ad={...base,source_id:'ad-day',rows:[],source_proof:{actual_source_ids:['ad:1']}};
  return{s:{rawFlows:[a,b],counted:f=>f.status!=='reference',c:{HTML2_STORE_HIERARCHY:{mode:()=>mode,setMode:v=>mode=v}},ledgers:new Map([['month|operations',[base,ad]],['month|finance',[base]]])},a,b};
 }
 it('费用可追溯两种口径，广告实际消耗只显示运营，不默认双口径',()=>{
  const {s,a,b}=runtime();expect(flowInclusion(s,a,null).mode_label).toBe('运营、财务');expect(flowInclusion(s,b,null).mode_label).toBe('运营');expect(s.c.HTML2_STORE_HIERARCHY.mode()).toBe('operations');
 });
 it('排除、核对项、未映射来源和待归属来源分别提示',()=>{
  const {s,a}=runtime();expect(flowInclusion(s,a,{excluded:true,change:{reason:'重复'}})).toMatchObject({mode_label:'不计入',reason:'重复'});
  expect(flowInclusion(s,{...a,status:'reference'},null).mode_label).toBe('不计入');
  expect(flowInclusion(s,{source_id:'unknown'},null).label).toBe('计入情况待核对');
  const pending=runtime();pending.s.ledgers.get('month|operations')[0].external_order_id='';expect(flowInclusion(pending.s,pending.a,null).mode_label).toContain('运营待核');
 });
 it('待核筛选包含缺汇率和未映射来源，核对项不会冒充正常计入',()=>{
  const {s}=runtime();s.p={localFact:f=>({...f,currency:'PHP',amount:f.amount})};
  expect(flowState(s,{source_id:'unknown',amount:'-1',currency:'PHP'},null)).toBe('pending');
  expect(flowState(s,{status:'reference'},null)).toBe('reference');
  s.p.localFact=f=>({...f,currency:'PHP',amount:null});expect(flowState(s,{amount:'-1',currency:'USD'},null)).toBe('pending');
 });
 it('同一来源存在已计入及待核部分时保留两种依据，顺序不改变结论',()=>{
  for(const reverse of [false,true]){
   const {s,a}=runtime(),rows=s.ledgers.get('month|operations'),pending={...rows[0],external_order_id:'',allocation_reason:'缺少分摊依据'};
   rows.push(pending);if(reverse)rows.reverse();const result=flowInclusion(s,a,null);
   expect(result.label).toBe('部分已计入，部分待核');expect(result.mode_label).toContain('运营（部分已计入，部分待核）');expect(result.reason).toContain('已知部分保持计入');expect(flowState({...s,p:{localFact:f=>f}},a,null)).toBe('pending');
  }
 });
 it('排除及仅核对状态不被缺汇率覆盖，折算问题独立保留',()=>{
  const {s,a}=runtime(),missing={missing:true};
  expect(flowStatus(a,flowInclusion(s,a,{excluded:true}),missing)).toBe('已排除（原额保留）');
  expect(flowStatus({...a,status:'reference'},null,missing)).toBe('仅核对，不计入');
  expect(flowStatus(a,{label:'已纳入汇总'},missing)).toBe('待核／缺汇率');
 });
 it('提前阻止已关账店铺记录和规则分摊记录编辑',()=>{
  const s={c:{HTML2_PROFIT_RULES:{closedFor:(shop,month)=>shop==='A'&&month==='2026-09'}}};
  expect(flowEditBlock(s,{store_code:'A',date:'2026-09-03'})).toContain('已关账');expect(flowEditBlock(s,{store_code:'B',date:'2026-09-03'})).toBe('');expect(flowEditBlock(s,{date:'2026-09-03',allocation_readonly:true})).toContain('规则分摊');
 });
});
