<script>
import { h, ref, watch, onMounted, onBeforeUnmount } from 'vue';
import { useRouter } from 'vue-router';
import { ElButton as Button, ElSelect as Select, ElOption as Option, ElInput as Input, ElTable as Table, ElTableColumn as Column, ElPagination as Pagination } from 'element-plus';
import request from '../../api/request';
import { useAuthStore } from '../../stores/auth';
import { cockpitActorKey } from '../../utils/cockpitDraft';
import ProductImage from '../../components/supply-chain/DocumentProductImageV2.vue';
import ABCBadges from '../../components/inventory/InventoryAbcBadges';
const labels={forecast_stockout:'预计断货',key_variant_shortage:'主要规格缺货',supply_risk:'供应到货风险',excess_stock:'库存积压',new_product:'新品观察',stock_without_sales:'有库存无销售',supply_overdue:'到货逾期',arrival_unconfirmed:'到货时间未定',new_product_observation:'新品观察',arrival_after_shortage:'到货晚于预计断货'};
const actions={forecast_stockout:'查看补货或调拨',key_variant_shortage:'优先补齐主要规格',supply_risk:'核实生产、发货及到货日期',excess_stock:'暂缓新增采购，检查动销',new_product:'观察规格销售表现'};
const fmt=v=>v==null?'—':v;
export default {name:'InventoryWarningRisk537',setup(){
 const auth=useAuthStore(),router=useRouter(),countries=ref([]),country=ref(''),search=ref(''),kind=ref('all'),page=ref(1),size=ref(20),data=ref({}),error=ref(''),busy=ref(false),children=ref({}),expandedKeys=ref([]);
 let seq=0,childEpoch=0,timer,attempts=0,controller,rebuildController,disposed=false;
 const childRequests=new Map();
 const actor=()=>cockpitActorKey(auth.currentUser);
 const daily=v=>v==null||String(v).trim()===''||!Number.isFinite(Number(v))?'—':Number(v).toFixed(2);
 function clearChildren(){childEpoch++;for(const c of childRequests.values())c.abort();childRequests.clear();children.value={};expandedKeys.value=[];}
 function cancel(){seq++;clearTimeout(timer);controller?.abort();rebuildController?.abort();clearChildren();busy.value=false;}
 function reset(){cancel();countries.value=[];country.value='';search.value='';kind.value='all';page.value=1;data.value={};error.value='';attempts=0;}
 async function load(resetPage=false){
  if(disposed||auth.authorizationStale||!actor())return;
  clearTimeout(timer);if(resetPage)page.value=1;const id=++seq;controller?.abort();const pending=new AbortController();controller=pending;clearChildren();busy.value=true;error.value='';
  data.value={...data.value,results:[]};
  try{
   const r=await request({method:'get',url:'/api/internal/alerts/inventory/warnings/',params:{country_id:country.value||undefined,search:search.value,warning_type:kind.value,page:page.value,page_size:size.value},signal:pending.signal});
   if(disposed||pending.signal.aborted||id!==seq)return;
   if(!r?.success)throw Error(r?.message||'读取预警快照失败');
   data.value=r.data||{};countries.value=r.data?.countries||[];
   if(['queued','building'].includes(r.data?.latest_status)&&attempts++<60)timer=setTimeout(()=>{if(id===seq&&!disposed)load();},10000);else attempts=0;
  }catch(e){if(!disposed&&!pending.signal.aborted&&id===seq){error.value=e.message;data.value={};}}
  finally{if(!disposed&&id===seq)busy.value=false;}
 }
 async function expand(row,expanded){
  const open=Array.isArray(expanded)?expanded.some(x=>x.spu_id===row.spu_id):expanded;
  expandedKeys.value=open?[...new Set([...expandedKeys.value,row.spu_id])]:expandedKeys.value.filter(k=>k!==row.spu_id);
  if(!open){childRequests.get(row.spu_id)?.abort();childRequests.delete(row.spu_id);return;}
  if(children.value[row.spu_id]||!country.value)return;
  childRequests.get(row.spu_id)?.abort();const pending=new AbortController();childRequests.set(row.spu_id,pending);
  const epoch=childEpoch,current=country.value,run=data.value.run_id;
  const valid=()=>!disposed&&!pending.signal.aborted&&epoch===childEpoch&&childRequests.get(row.spu_id)===pending&&current===country.value&&run===data.value.run_id;
  try{
   const r=await request({method:'get',url:'/api/internal/alerts/inventory/warnings/',params:{country_id:current,spu_id:row.spu_id},signal:pending.signal});
   if(!valid())return;
   if(!r?.success)throw Error(r?.message||'明细读取失败');
   if(r.data?.run_id!==run)throw Error('库存预警已更新，请重新查询后展开。');
   children.value={...children.value,[row.spu_id]:r.data.results||[]};
  }catch(e){if(valid())error.value=e.message;}
  finally{if(childRequests.get(row.spu_id)===pending)childRequests.delete(row.spu_id);}
 }
 async function rebuild(){
  if(!country.value||disposed||auth.authorizationStale||!auth.hasPermission('alerts.evaluate'))return;
  rebuildController?.abort();const pending=new AbortController();rebuildController=pending;const owner=actor(),id=seq;busy.value=true;
  const valid=()=>!disposed&&!pending.signal.aborted&&owner===actor()&&id===seq;
  try{const r=await request({method:'post',url:'/api/internal/alerts/inventory/warnings/rebuild/',data:{country_id:Number(country.value)},signal:pending.signal});if(!valid())return;if(!r?.success)throw Error(r?.message||'提交失败');await load();}
  catch(e){if(valid())error.value=e.message;}
  finally{if(valid())busy.value=false;}
 }
 watch(()=>[actor(),auth.authorizationStale,auth.currentUser],()=>{reset();if(!auth.authorizationStale&&actor())load();},{deep:true,flush:'sync'});
 onMounted(()=>load());onBeforeUnmount(()=>{disposed=true;cancel();});
 const col=(label,render,width)=>h(Column,{label,minWidth:width||130},{default:({row})=>render(row)});
 const text=(v,small=false)=>h(small?'small':'div',{style:small?'display:block;color:#64748b;margin-top:4px':''},v);
 const tags=items=>h('div',null,(items||[]).map(k=>h('span',{style:'display:inline-block;padding:3px 7px;margin:2px 4px 2px 0;border-radius:4px;background:'+(k==='forecast_stockout'||k==='key_variant_shortage'?'#fff1f0;color:#c53030':'#eff6ff;color:#2458a6')},labels[k]||k)));
 const product=row=>h('div',{style:'display:flex;gap:10px;align-items:center'},[row.image_preview_url?h(ProductImage,{imagePath:row.image_preview_url,alt:row.spu_name||row.product_name||'商品图片'}):null,h('div',null,[text(row.spu_name||row.product_name||row.sku_code||row.sku),text('新编码：'+(row.sku_code||row.sku||row.spu_code||'—'),true),text('旧编码：'+(row.legacy_sku_code||row.legacy_spu_code||'—'),true),row.first_sale_date?text('首销日期：'+row.first_sale_date,true):null,row.abc?h(ABCBadges,{row,entityType:row.sku_id?'sku':'spu'}):null])]);
 const skuTable=rows=>h(Table,{data:rows||[],stripe:true,border:true,rowKey:'sku_id'},()=>[
 col('商品 / SKU',product,270),col('当前可售库存',r=>fmt(r.available_stock??r.stock)),
 col('销量 / 日均',r=>[text('日均 '+daily(r.daily_sales)),...(r.sales_windows||[]).map(w=>text(w.days+'天：'+fmt(w.units),true))],150),
 col('风险与预计日期',r=>[tags(r.warning?.warnings),text(r.warning?.first_shortage_date?(r.warning.confidence==='reference'?'参考预计断货 ':'预计断货 ')+r.warning.first_shortage_date:(r.warning?.state==='unavailable'?'当前资料不足以预测断货':'所看周期内暂无预计断货'),true)],220),
 col('生产与到货',r=>[text('生产中 '+fmt(r.warning?.production_unshipped)),text('逾期未到 '+fmt(r.warning?.overdue_quantity),true),text('日期未定 '+fmt(r.warning?.unknown_arrival_quantity),true),text('最近预计到货 '+fmt(r.warning?.next_confirmed_arrival_date),true)],170),
 col('缺口 / 建议',r=>[text('预计最大缺口 '+fmt(r.warning?.maximum_shortage_quantity)),text((r.warning?.warnings||[]).includes('forecast_stockout')?'优先查看已有采购能否按期到货':'结合整款规格判断采购',true),auth.hasPermission('replenishment.view')?h(Button,{link:true,type:'primary',onClick:()=>router.push({path:'/inventory/replenishment',query:{country_id:country.value,search:r.sku_code||r.sku||r.legacy_sku_code||''}})},{default:()=>'查看补货建议'}):null],230)]);
 return()=>h('section',{style:'padding:20px;color:#26364a',onVnodeBeforeUnmount:cancel},[
 h('div',null,[h('h2',{style:'margin:0 0 8px'},'库存预警'),text('按国家查看整款风险，展开比较各规格库存、销量和到货情况。',true),
 h('div',{style:'display:flex;flex-wrap:wrap;gap:12px;margin:18px 0;padding:16px;background:white;border:1px solid #e2e8f0;border-radius:6px'},[
 h(Select,{modelValue:country.value,'onUpdate:modelValue':v=>{country.value=v;data.value={};},placeholder:'选择国家',style:'width:220px','aria-label':'预警国家',onChange:()=>load(true)},()=>countries.value.map(c=>h(Option,{label:c.name+' ('+c.country_code+')',value:c.id}))),
 h(Input,{modelValue:search.value,'onUpdate:modelValue':v=>search.value=v,placeholder:'搜索名称 / 新旧 SPU、SKU',clearable:true,style:'width:280px',onKeyup:e=>{if(e.key==='Enter')load(true);}}),
 h(Select,{modelValue:kind.value,'onUpdate:modelValue':v=>kind.value=v,style:'width:200px','aria-label':'库存风险类型',onChange:()=>load(true)},()=>[h(Option,{label:'全部库存情况',value:'all'}),...['forecast_stockout','key_variant_shortage','supply_risk','excess_stock','new_product'].map(k=>h(Option,{label:labels[k],value:k}))]),
 h(Button,{type:'primary',loading:busy.value,onClick:()=>load(true)},{default:()=>'查询'}),auth.hasPermission('alerts.evaluate')?h(Button,{disabled:!country.value,loading:busy.value,onClick:rebuild},{default:()=>'后台更新'}):null]),
 error.value?h('p',{role:'alert',style:'color:#c53030'},error.value):null,
 data.value.summary?h('div',{style:'display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:14px'},['forecast_stockout','key_variant_shortage','supply_risk','excess_stock','new_product'].map(k=>h('button',{onClick:()=>{kind.value=k;load(true);},style:'text-align:left;background:white;border:1px solid #e2e8f0;border-radius:6px;padding:16px;color:#334155;cursor:pointer'},[text(labels[k]),h('strong',{style:'display:block;font-size:25px;margin-top:10px'},String(data.value.summary[k]||0)+' 款')]))):null,
 text(!country.value?'请选择国家查询。':!data.value.run_id?'尚无已完成结果，可提交后台更新。':('本次共 '+(data.value.count||0)+' 款 · 更新 '+new Date(data.value.updated_at).toLocaleString('zh-CN')+(data.value.status==='partial'?' · 部分资料尚未齐全，含参考估算，请结合实际到货复核':'')+(['queued','building'].includes(data.value.latest_status)?' · 后台正在更新，当前显示上次完成结果':data.value.latest_status==='failed'?' · 本次更新未完成，当前显示上次完成结果':'')),true),
 data.value.config?.unmapped_stock_records?text('另有 '+data.value.config.unmapped_stock_records+' 条有库存的仓库商品尚未关联商品档案，请在仓库库存明细核实；这些商品未被当成零库存。',true):null,
 h(Table,{data:data.value.results||[],stripe:true,border:true,rowKey:'spu_id',expandRowKeys:expandedKeys.value,onExpandChange:expand,style:'margin-top:14px'},()=>[
 h(Column,{type:'expand'},{default:({row})=>h('div',{style:'padding:14px'},children.value[row.spu_id]?[skuTable(children.value[row.spu_id])]:['正在读取规格明细…'])}),col('商品 / SPU',product,300),col('规格情况',r=>[text(r.sku_count+' 个规格'),text(r.shortage_sku_count+' 个规格预计断货',true)],150),col('库存风险',r=>[tags(r.warnings),r.incomplete_sku_count?text(r.incomplete_sku_count+' 个规格暂不能预测',true):null],260),col('最早预计断货',r=>(r.confidence==='reference'&&r.first_shortage_date?'参考 ':'')+fmt(r.first_shortage_date),150),col('建议动作',r=>(r.warnings||[]).map(k=>text(actions[k]||labels[k],true)),230)]),
 h(Pagination,{'current-page':page.value,'onUpdate:currentPage':v=>page.value=v,'page-size':size.value,'onUpdate:pageSize':v=>size.value=v,total:data.value.count||0,'page-sizes':[20,50,100],layout:'total, sizes, prev, pager, next',onChange:()=>load(),style:'margin-top:16px'})])]);
}};

</script>
