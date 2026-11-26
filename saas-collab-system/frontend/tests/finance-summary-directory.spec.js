import {it,expect,vi} from 'vitest';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {directoryOptions}=require('../../backend/apps/finance/summary_native.cjs');
function session(){
 const statisticsDate=vi.fn(()=> '2026-08-20');
 const fact={store_id:1,store_code:'A',country:'PH',platform:'shopee',currency:'PHP',month:'2026-09',date:'2026-09-01'};
 Object.defineProperty(fact,'statistics_date',{get:statisticsDate,enumerable:true});
 return {statisticsDate,p:{entriesFor:()=>[fact],displayCurrency:f=>f.currency},c:{LEDGER_FEES:{shops:()=>[{id:2,code:'LZ2',country:'MY',currency:'MYR'}],kinds:['sales']},HTML2_PROFIT_RULES:{closed:()=>({'A|2026-09':{shop:'A',month:'2026-09'}})}},countries:{PH:'菲律宾',MY:'马来西亚'},labels:{sales:'销售额',order_fee:'订单费用'}};
}
it('数据库目录只生成最终日历，合并成本和原始流水月份且保留筛选字段',()=>{
 const s=session();s.costFlows=[{date:'2026-10-01'}];s.rawFlows=[{date:'2026-11-01',kind:'order_fee',original_currency:'USD'}];
 const options=directoryOptions(s);
 expect(options.months).toEqual(['2026-11','2026-10','2026-09']);expect(s.statisticsDate).not.toHaveBeenCalled();
 expect(options.periods_by_month['2026-09'].half_month.map(r=>r.value)).toEqual(['2026-09-16','2026-09-01']);
 expect(options.stores.map(r=>r.code)).toEqual(['A','LZ2']);expect(options.raw_flows).toBe(true);
 expect(options.kinds.map(r=>r.key)).toEqual(['order_fee','sales']);expect(options.editable_kinds.map(r=>r.key)).toEqual(['sales']);
 expect(options.currencies).toEqual(['USD','PHP','MYR']);expect(options.closed_periods).toEqual([{shop:'A',month:'2026-09'}]);
});
it('旧批次没有原始流水或成本数组时保留账期内跨月归期目录',()=>{
 const s=session(),options=directoryOptions(s);
 expect(options.periods_by_month['2026-09'].half_month.map(r=>r.value)).toEqual(['2026-09-16','2026-09-01','2026-08-16']);
 expect(s.statisticsDate).toHaveBeenCalled();expect(options.raw_flows).toBeUndefined();
 const empty=session();empty.costFlows=[];
 expect(directoryOptions(empty).periods_by_month['2026-09'].half_month).toHaveLength(2);expect(empty.statisticsDate).not.toHaveBeenCalled();
});
