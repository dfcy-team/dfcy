import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';

const source=fs.readFileSync(path.resolve('../backend/apps/finance/summary_runtime.js'),'utf8');
function runtime(){
 const c={state:{filters:{month:'2026-09'}},HTML2_FEE_RATES:{displayAmount:n=>n},countedFact:()=>true,localFact:f=>f,micro:n=>BigInt(n),ledgerParts:f=>f.parts||[]};
 c.mode='operations';c.parents=[];c.HTML2_STORE_HIERARCHY={mode:()=>c.mode,setMode:m=>{c.mode=m;},controls:()=>c.parents};
 vm.createContext(c);vm.runInContext(source,c);return c;
}
describe('财务展示缓存与子费率追溯',()=>{
 it('缓存区分筛选与口径，设置变更后不复用旧结果',()=>{const c=runtime();let calls=0;const f=c.SAAS_MEMO(()=>++calls);expect(f()).toBe(1);expect(f()).toBe(1);c.state.filters.month='2026-08';expect(f()).toBe(2);c.mode='finance';expect(f()).toBe(3);c.SAAS_INVALIDATE();expect(f()).toBe(4);});
 it('按本行已分摊额拆分原始子项，保留费用返还方向及合计',()=>{const c=runtime();c.parents=[{store_id:58,month:'2026-09',currency:'THB',kind:'order_fee',external_order_id:'order',parts:[{leaf:true,status:'confirmed',label:'佣金',amount:-80n},{leaf:true,status:'confirmed',label:'手续费',amount:-20n},{leaf:true,status:'confirmed',label:'费用返还',amount:10n}]}];const data={sku:true,group:{members:[{store:'58',month:'2026-09',currency:'THB',orders:['shopee|58|order'],amounts:{order_fee:-45n}}]},fees:{order_fee:{amount:-45n}}};const parts=c.SAAS_FEE_PARTS(data,'order_fee');expect(parts.map(r=>r.amount)).toEqual([-40n,-10n,5n]);expect(parts.reduce((n,r)=>n+r.amount,0n)).toBe(-45n);});
 it('缺少可靠来源时不冒充已细分项目，广告不继承销售商品字段',()=>{const c=runtime();const data={sku:true,group:{members:[{store:'58',month:'2026-09',currency:'THB',orders:[],amounts:{order_fee:-45n}}]},fees:{order_fee:{amount:-45n}}};expect(c.SAAS_FEE_PARTS(data,'order_fee')[0].label).toBe('来源待细分（已分摊）');c.parents=[{store_id:58,month:'2026-09',currency:'THB',kind:'advertising',sp6th_components:[{label:'商品销售额',field:'order_selling_price',amount:'1000'}],parts:[{leaf:true,status:'confirmed',label:'广告消耗',amount:-100n}]}];const group={members:[{store:'58',month:'2026-09',currency:'THB',orders:[],amounts:{advertising:-50n}}]};expect(c.SAAS_FEE_PARTS({sku:true,operations:group,fees:{operations:{amount:-50n}}},'operations')[0].label).toBe('广告消耗');});
 it('原始子项取消计入后，子费率构成同步排除',()=>{const c=runtime();c.FEE_CHECKBOXES={getExcluded:()=>({excluded:true}),key:(f,r)=>r.key};c.parents=[{store_id:58,month:'2026-09',currency:'THB',kind:'order_fee',parts:[{leaf:true,key:'excluded',status:'confirmed',label:'取消计入项',amount:-20n},{leaf:true,key:'included',status:'confirmed',label:'手续费',amount:-80n}]}];const data={sku:true,group:{members:[{store:'58',month:'2026-09',currency:'THB',orders:[],amounts:{order_fee:-40n}}]},fees:{order_fee:{amount:-40n}}};expect(c.SAAS_FEE_PARTS(data,'order_fee').map(r=>r.label)).toEqual(['手续费']);});
});
