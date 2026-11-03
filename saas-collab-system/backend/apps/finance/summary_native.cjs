// Read-only, version-scoped calculation process. No network and no posting APIs.
const readline=require('node:readline'),vm=require('node:vm'),fs=require('node:fs');
const {createEngine,plain}=require('./summary_engine.cjs'),sessions=new Map();
const {costDetail}=require('./summary_cost_detail.cjs');
const {orderLedger,itemMembers,groupMembers,groupLinks,orderAttribution,attributionTotals,itemAttribution}=require('./summary_order_ledger.cjs');
const {periodOptions,periodRange,inPeriod,datedFact}=require('./summary_periods.cjs');
const feeKinds=['sales','refund','order_fee','adjustment','shop_adjustment','operations','finance','product_cost','gcash','promotion','warehouse_order','warehouse_other'];
const flowDate=f=>Object.hasOwn(f,'period_date')?f.period_date:Object.hasOwn(f,'statistics_date')?f.statistics_date:f.date;
function open(request){
 if(sessions.has(request.key))return sessions.get(request.key);
 const s=createEngine(request.path,request.input,{memo:true}),{c,p}=s;
 s.sourceScope=request.input.sourceScope;
 vm.runInContext(fs.readFileSync(__dirname+'/summary_runtime.js','utf8'),c);
 s.rates=c.HTML2_FEE_RATES;s.counted=vm.runInContext('countedFact',c);s.parts=vm.runInContext('ledgerParts',c);s.labels=vm.runInContext('KINDS',c);s.countries=vm.runInContext('COUNTRY',c);s.queries=new Map();s.ledgers=new Map();
 const facts=p.entriesFor('store'),shops=new Map(facts.filter(f=>f.store_id).map(f=>[String(f.store_id),{id:String(f.store_id),code:f.store_code,country:f.country,platform:f.platform,currency:p.displayCurrency(f)}]));
 for(const shop of c.LEDGER_FEES.shops())if(!shops.has(String(shop.id)))shops.set(String(shop.id),{...shop,id:String(shop.id),platform:shop.code.startsWith('LZ')?'lazada':'shopee'});
 s.options={stores:[...shops.values()].sort((a,b)=>a.code.localeCompare(b.code)),countries:s.countries,months:[...new Set(facts.map(f=>String(f.month||f.date).slice(0,7)))].filter(Boolean).sort().reverse(),kinds:c.LEDGER_FEES.kinds.map(k=>({key:k,label:s.labels[k]||k}))};
 s.options.periods_by_month=Object.fromEntries(s.options.months.map(m=>[m,periodOptions(m,facts.filter(f=>String(f.month||f.date).slice(0,7)===m).map(f=>datedFact(f,new Map()).period_date))]));
 if(sessions.size>=1)sessions.delete(sessions.keys().next().value);sessions.set(request.key,s);return s;
}
function query(s,view,filters,mode,scope='store'){
 const key=JSON.stringify([view,filters,mode,scope]);s.c.HTML2_STORE_HIERARCHY.setMode(mode);
 if(s.queries.has(key))return s.queries.get(key);
 const rows=calculate(s,view,filters,mode,scope);if(s.queries.size>=4)s.queries.delete(s.queries.keys().next().value);s.queries.set(key,rows);return rows;
}
function calculate(s,view,filters,mode,scope='store'){
 const {c,p}=s,type=filters.period_type||'month',key=type+'|'+mode;c.HTML2_STORE_HIERARCHY.setMode(mode);
 if(!s.ledgers.has(key)){if(s.ledgers.size>=2)s.ledgers.delete(s.ledgers.keys().next().value);s.ledgers.set(key,orderLedger(s,type,mode));}
 const selected=s.ledgers.get(key).filter(f=>p.matches(f,{...filters,order:view==='sku'||view==='product_link'?'':filters.order,sku:''})&&inPeriod(f,type,filters.period));
 const pending=filters.attribution==='pending';
 const facts=selected.filter(f=>pending?!!orderAttribution(s,f)&&!/^database:coverage:/.test(f.source_id||'')&&(f.amount==null||p.micro(f.amount)!==0n):!orderAttribution(s,f));
 if(view==='detail')return facts.filter(r=>{
  const can=!r.allocation_readonly&&c.LEDGER_FEES.editable(r)&&!!r.ledger_key,status=r.ledger_disabled?'disabled':r.ledger_added?'added':r.ledger_adjusted?'modified':r.amount==null||r.statistics_date_reason||!flowDate(r)?'pending':'normal',text=[r.source,r.description,r.allocation_reason,r.statistics_date_reason,...(r.ledger_original?.rows||r.rows||[]).map(x=>x.name)].join(' ').toLowerCase(),day=flowDate(r);
  return(!(filters.from||filters.to)||/^\d{4}-\d{2}-\d{2}$/.test(day||''))&&(!filters.from||day>=filters.from)&&(!filters.to||day<=filters.to)&&(!filters.kind||r.kind===filters.kind)&&(!filters.keyword||text.includes(filters.keyword.toLowerCase()))&&(!filters.status||(filters.status==='readonly'?!can:status===filters.status))&&(!filters.editable||can);
 }).sort((a,b)=>String(flowDate(b)||b.month).localeCompare(String(flowDate(a)||a.month)));
 if(['country','store','order'].includes(view)){
  const groups=p.groupRows(facts.map(f=>f.external_order_id?f:{...f,external_order_id:'待分摊（无订单归属）',hierarchy_pending:f.status!=='reference'&&(f.amount==null||p.micro(f.amount)!==0n)}),view);
  for(const g of groups)g.pending=!!g.pending||Object.values(g.cells).some(cell=>cell.entries.some(f=>f.hierarchy_pending));
  return groups;
 }
 const members=itemMembers(s,facts,s.ledgers.get(key)),sku=groupMembers(s,members,scope==='product'&&view==='sku'?'product':'store');
 if(view==='product_link'){const term=(filters.product||'').toLowerCase();return groupLinks(s,sku,facts).filter(g=>!term||[g.title,g.product_id].some(x=>String(x||'').toLowerCase().includes(term)));}
 const term=(filters.sku||'').toLowerCase();return sku.filter(g=>!term||[...g.codes,...g.legacy,...g.platform_skus].some(x=>String(x||'').toLowerCase().includes(term)));
}
function cell(s,g,kind,sku){
 const value=s.rates.read(g,kind,sku),entries=sku?[]:g?.cells[kind]?.entries||[];
 if(entries.length&&entries.every(f=>f.amount==null||kind==='product_cost'&&f.cost_calculation?.components?.length&&f.cost_calculation.components.every(c=>Object.hasOwn(c,'unit_cost')&&c.unit_cost==null||c.reasons?.length)))return{amount:null,partial:true};
 return value;
}
function amount(s,value){return value==null?null:s.p.fixed(value);}
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function factHtml(s,f){
 const a=f.hierarchy_allocation,explanation=[orderAttribution(s,f),f.period_date_basis,f.allocation_reason,f.statistics_date_reason].filter(Boolean).join('；');
 return (orderAttribution(s,f)?'<p>当前记录仅在待核对区保留，不计入正式订单汇总及利润。下方原始构成用于核对来源，不表示已完成订单归属。</p>':'')+s.p.factDetails(f.public_fee_evidence?{...f,hierarchy_allocation:undefined}:f)+(explanation?'<h3>归期与分摊依据</h3><p>'+esc(explanation)+'</p>':'')+
  (a?'<p>来源控制额：'+esc(a.parent_amount)+'；订单分子：'+esc(a.order_sales||a.order_quantity)+'；完整分母：'+esc(a.store_sales||a.store_quantity)+'；来源ID：'+esc((a.source_ids||[]).join('、'))+'</p>':'')+
  (f.advertising_evidence?'<h3>本分摊费用池来源（不是再次计费）</h3><table><tr><th>来源日期</th><th>费用池原金额</th><th>来源依据</th></tr>'+f.advertising_evidence.map(r=>'<tr><td>'+esc(r.date||'待归期')+'</td><td>'+esc(r.amount)+' '+esc(f.currency)+'</td><td>'+esc([r.source_id,...(r.proof?.actual_source_ids||[]),...(r.proof?.recharge_source_ids||[])].join('、'))+'</td></tr>').join('')+'</table>':'')+
  (f.public_fee_evidence?'<h3>公共费用原始来源（不是再次计费）</h3><p>'+esc(f.public_fee_evidence.date||'待归期')+' · '+esc(f.public_fee_evidence.source)+' · '+esc(f.public_fee_evidence.amount)+' '+esc(f.public_fee_evidence.currency)+'</p><p>'+esc(f.public_fee_evidence.fee_names.join('、'))+'；来源ID：'+esc(f.public_fee_evidence.source_id)+'</p>':'');
}
function rowKey(g,i){return String(g.key||g.allocation_key||g.ledger_key||g.source_id||'row:'+i);}
function identity(s,g,view){
 const member=g.members?.[0],fact=Object.values(g.cells||{}).flatMap(x=>x.entries)[0],store=g.store_id||member?.store||g.store;
 return{country:s.countries[g.country]||g.country,platform:g.platform||member?.platform||fact?.platform||'',store:store?String(store):'',shop:g.shop||g.store_code||(g.shops?[...g.shops].join('、'):fact?.store_code)||'待归属店铺',currency:g.currency,order:g.external_order_id||'',sku:g.code||'',title:g.title||g.reason||g.code||'',product_id:g.product_id||'',url:g.url||'',sku_count:g.skus?.length||0};
}
function table(s,input){
 const {view,filters={},mode='operations',scope='store',page=1,page_size=20}=input,sku=['sku','product_link'].includes(view);
 const range=filters.period_type&&filters.period_type!=='month'&&filters.period&&filters.period!=='undated'?periodRange(filters.period_type,filters.period):null;
 const boundary=!!(range&&s.sourceScope&&(range.from<s.sourceScope.from||range.to>s.sourceScope.to));
 if(filters.attribution==='pending'&&view!=='detail')throw Error('待归属金额仅作为独立明细核对，不生成虚拟店铺或利润。');
 const ops=query(s,view,filters,view==='detail'?mode:'operations',scope),fin=view==='detail'?[]:query(s,view,filters,'finance',scope),opMap=new Map(ops.map((g,i)=>[rowKey(g,i),g])),finMap=new Map(fin.map((g,i)=>[rowKey(g,i),g]));
 const base=view==='detail'?ops:[...new Map((mode==='finance'?fin.concat(ops):ops.concat(fin)).map((g,i)=>[rowKey(g,i),g])).values()];
 const current=Math.min(page,Math.max(1,Math.ceil(base.length/page_size))),rows=base.slice((current-1)*page_size,current*page_size).map((g,i)=>{
  const key=rowKey(g,(current-1)*page_size+i);if(view==='detail'){
   const can=!g.allocation_readonly&&s.c.LEDGER_FEES.editable(g)&&(g.kind==='advertising'||g.amount!=null)&&!!g.ledger_key,original=g.ledger_original?s.p.localFact(g.ledger_original).amount:g.ledger_record?.amount??g.amount;
   const attribution=orderAttribution(s,g);
   return{key,edit_key:g.ledger_key,identity:{country:s.countries[g.country]||g.country,store:String(g.store_id||''),shop:g.store_code||'国家公共费用',currency:g.currency,order:g.external_order_id||''},date:flowDate(g)||'待归期',date_basis:g.period_date_basis||g.statistics_date_basis||'',accounting_date:g.date,accounting_month:String(g.month||g.date).slice(0,7),source_bill_month:g.source_bill_month,date_reason:g.statistics_date_reason||'',kind:g.kind,label:s.labels[g.kind]||g.kind,mode:g.ledger_ad_mode||g.ledger_record?.mode||'both',amount:g.amount,original_amount:original,status:g.ledger_disabled?'已禁用':g.status==='reference'?'仅核对，不计入':attribution?'待归属订单（不计入正式汇总）':g.ledger_added?'新增费用':g.ledger_adjusted?'已修改':g.amount==null?'待核／缺汇率':!flowDate(g)?'待归期':g.allocation_readonly?'规则分摊（只读）':'正常',source:g.source,description:[attribution,g.description,g.allocation_reason,g.period_date_basis,g.statistics_date_reason].filter(Boolean).join('；'),editable:can,added:!!g.ledger_added,disabled:!!g.ledger_disabled,record:g.ledger_record||null};
  }
  const operation=opMap.get(key),finance=finMap.get(key),values={},partial={};
  for(const kind of feeKinds){const isAd=['operations','finance'].includes(kind),r=cell(s,isAd?(kind==='operations'?operation:finance):g,isAd?'advertising':kind,sku);values[kind]=amount(s,r.amount);partial[kind]=r.partial;}
  const profits={operations:s.rates.profit(operation,sku),finance:s.rates.profit(finance,sku)},sales=cell(s,g,'sales',sku),cost=cell(s,g,'product_cost',sku),denominator=sales.partial?null:sales.amount,rates={};
  for(const [kind]of s.rates.fields)rates[kind]=kind==='gross_margin'?s.rates.grossMargin(denominator,cost.amount):kind.startsWith('profit_')?s.rates.ratio(profits[kind.slice(7)],denominator,true).replace(/^\+/,''):s.rates.ratio(values[kind]==null?null:s.p.micro(values[kind]),denominator,['adjustment','shop_adjustment'].includes(kind));
  return{key,identity:identity(s,g,view),values,partial,profits:{operations:amount(s,profits.operations),finance:amount(s,profits.finance)},rates,pending:boundary||!!g.pending||Object.values(values).some(x=>x==null)||Object.values(partial).some(Boolean)};
 });
 const undated=query(s,'detail',{...filters,from:'',to:'',kind:'warehouse_order',status:'',keyword:'',editable:''},mode).filter(f=>f.statistics_date_reason).length;
 const totals=[];let itemGaps=[];
 const common=Object.fromEntries(['month','country','platform','store','currency'].map(k=>[k,filters[k]||'']));
 if(!s.attributionReports)s.attributionReports=new Map();
 for(const basis of ['operations','finance']){
  const type=filters.period_type||'month',key=JSON.stringify([basis,type,filters.period,common]);
  if(!s.attributionReports.has(key)){
   const ledger=orderLedger(s,type,basis),facts=ledger.filter(f=>s.p.matches(f,common)&&inPeriod(f,type,filters.period));
   if(s.attributionReports.size>=4)s.attributionReports.delete(s.attributionReports.keys().next().value);
   s.attributionReports.set(key,{totals:attributionTotals(s,facts),item_gaps:itemAttribution(s,facts.filter(f=>!orderAttribution(s,f)),ledger)});
  }
  const report=s.attributionReports.get(key);
  totals.push(...report.totals.filter(g=>g.total!=='0.000000'||g.pending_rows||g.unknown_rows).map(g=>({...g,mode:basis,label:s.labels[g.kind]||g.kind,country:s.countries[g.country]||g.country})));
  if(basis===mode)itemGaps=report.item_gaps;
 }
 const attribution={totals,item_gaps:itemGaps,pending_rows:totals.filter(g=>g.mode===mode).reduce((n,g)=>n+g.pending_rows,0)};
 if(view!=='detail')for(const row of rows)if(itemGaps.some(g=>row.identity.shop===g.store||view==='country'&&s.options.stores.some(shop=>shop.code===g.store&&s.countries[shop.country]===row.identity.country)))row.pending=true;
 return{view,mode,rows,total:base.length,page:current,page_size,options:s.options,labels:s.labels,rate_fields:s.rates.fields,attribution,allocation_version:'order-ledger-v3',period_warning:boundary?`本周期超出已接入范围（${s.sourceScope.from} — ${s.sourceScope.to}），仅计算已载入部分，不认定完整周期；未自动补采数据。`:'',period_note:'正式汇总共用已归属订单明细。未关联／未分摊的仓库处理费及仓库其他费不参与本次汇总，也不进入待核对；原登记保留不动。无订单的订单调整、公共订单费用及店铺调整按同店同币种所选月／自然周／半月的有效结算销售额分摊，直接关联订单的调整不重摊。其他来源确实缺金额、日期或同期分母时才保留待核对；订单内缺商品依据仍明确标记。已关联仓库费用、成本及汇率规则不变。',date_warning:undated?`${undated}笔已关联出库处理费缺少唯一发货／揽收日期，金额保留在原账期及待归期，不混入未关联费用待核对区。已关联仓库其他费沿用对应订单归期。`:''};
}
function detail(s,input){
 const {view,filters={},scope='store',mode='operations',row_key,kind}=input,sku=['sku','product_link'].includes(view),rows=query(s,view,filters,mode,scope),g=rows.find((x,i)=>rowKey(x,i)===row_key);
 if(!g)throw Error('该行已变化，请刷新后重试。');
 if(view==='detail')return{title:(s.labels[g.kind]||g.kind)+' · 来源及核算依据',html:factHtml(s,g),records:[]};
 const isRate=kind.startsWith('rate:'),k=isRate?kind.slice(5):kind,ad=['operations','finance'].includes(k),targetKind=ad?'advertising':k;
 if(ad&&mode!==k)return detail(s,{...input,mode:k});
 if(k.startsWith('profit_')&&mode!==k.slice(7))return detail(s,{...input,mode:k.slice(7)});
 const read=cell(s,g,targetKind,sku),sales=cell(s,g,'sales',sku),cost=cell(s,g,'product_cost',sku),net=k.startsWith('profit_'),gross=k==='gross_margin',target=gross?(sales.amount==null||cost.amount==null?null:s.rates.displayAmount(sales.amount)+s.rates.displayAmount(cost.amount)):net?s.rates.profit(g,sku):read.amount;
 if(k==='product_cost'){
  let entries=sku?(g.members||g.skus?.flatMap(x=>x.members)||[]).filter(m=>m.fact?.kind==='product_cost').map((m,i)=>({
   ...m.fact,amount:m.amounts.product_cost==null?null:s.p.fixed(m.amounts.product_cost),currency:g.currency,
   cost_detail_key:(m.fact.ledger_key||m.fact.source_id||'cost')+':component:'+i,
   status:m.component?.reasons?.length||m.amounts.product_cost==null?'pending':'confirmed',
   cost_calculation:{...m.fact.cost_calculation,state:m.component?.reasons?.length||m.amounts.product_cost==null?'pending':'calculated',components:m.component?[m.component]:[]}})):g.cells.product_cost?.entries||[];
  let currentTarget=target,currentSales=sales.partial?null:sales.amount,currentPartial=read.partial;
  if(input.source_key){
   const f=entries.find((f,i)=>String(f.cost_detail_key||f.ledger_key||f.source_id||i)===input.source_key);
   if(!f)throw Error('来源记录已变化，请重新打开。');
   entries=[f];currentTarget=f.amount==null?null:s.p.micro(f.amount);currentPartial=f.cost_calculation?.state==='pending';
   const order=query(s,'order',{...filters,store:String(f.store_id),order:f.external_order_id},mode,scope).find(x=>x.external_order_id===f.external_order_id&&x.currency===f.currency);
   const orderSales=order?cell(s,order,'sales',false):null;currentSales=orderSales&&!orderSales.partial?orderSales.amount:null;
  }
  const level=['country','store'].includes(view)&&!input.source_key?'orders':'items';
  const parts=level==='orders'?[]:s.c.FINANCE_COMPOSITION.fromEntries(entries,currentTarget);
  return costDetail(s,{entries,parts,target:currentTarget,partial:currentPartial,sales:currentSales,input,level});
 }
 let parts=[],records=[];
 if(gross)parts=[{label:'订单销售额',amount:sales.amount},{label:'商品净成本',amount:cost.amount}];
 else if(net)parts=Object.keys(sku?g.amounts:g.cells).map(key=>({label:s.labels[key]||key,amount:cell(s,g,key,sku).amount}));
 else if(sku){
  const members=(g.members||g.skus?.flatMap(part=>part.members)||[]).filter(m=>Object.hasOwn(m.amounts,targetKind));
  if(input.source_key){const m=members[Number(String(input.source_key).replace(/^member:/,''))];if(!m||!String(input.source_key).startsWith('member:'))throw Error('来源记录已变化，请重新打开。');return{title:'订单到当前SKU／链接的费用份额',html:factHtml(s,m.fact)+'<p>订单核算金额：'+esc(m.fact.amount)+'；当前份额：'+esc(m.amounts[targetKind]==null?'待核':s.p.fixed(m.amounts[targetKind]))+' '+esc(g.currency)+'；'+esc(m.hierarchy_basis)+'</p>',records:[]};}
  records=members.map((m,i)=>({key:'member:'+i,date:flowDate(m.fact)||'待归期',shop:m.shop,order:m.fact.external_order_id,source:m.fact.source,description:m.hierarchy_basis,amount:m.amounts[targetKind]==null?null:s.p.fixed(m.amounts[targetKind]),currency:m.currency}));
  const data={sku:true,group:g,[k]:g,fees:{[k]:{amount:target}}};parts=s.c.FINANCE_COMPOSITION.build(data,k);
 }
 else{
  const entries=g.cells[targetKind]?.entries||[];
  if(input.source_key){const f=entries.find((f,i)=>String(f.allocation_key||f.ledger_key||f.source_id||i)===input.source_key);if(!f)throw Error('来源记录已变化，请重新打开。');return{title:'原始金额来源',html:factHtml(s,f),records:[]};}
  records=entries.map((f,i)=>({key:String(f.allocation_key||f.ledger_key||f.source_id||i),date:flowDate(f)||'待归期',shop:f.store_code,order:f.external_order_id,source:f.source,description:[f.description,f.allocation_reason,f.period_date_basis].filter(Boolean).join('；'),amount:f.amount,currency:f.currency}));
  parts=s.c.FINANCE_COMPOSITION.fromEntries(entries,target);
 }
 const rounded=parts.map(r=>({...r,amount:s.rates.displayAmount(r.amount)})),total=s.rates.displayAmount(target),sum=rounded.filter(r=>r.included!==false).reduce((n,r)=>n+(r.amount||0n),0n);
 if(total!=null&&sum!==total)rounded.push({label:'显示精度／来源待细分差额',amount:total-sum});
 const signed=gross||net||['adjustment','shop_adjustment'].includes(k),denom=sales.partial?null:sales.amount;
 return{title:(isRate?s.rates.fields.find(x=>x[0]===k)?.[1]:s.labels[targetKind]||k)+' · 构成',amount:amount(s,total),sales:amount(s,denom),rate:s.rates.ratio(signed?total:total==null?null:total<0n?-total:total,denom,true).replace(/^\+/,''),parts:rounded.map(r=>({label:r.label,level:r.level||2,subtotal:r.leaf===false,included:r.included!==false,status:r.status,source:r.source||'',amount:amount(s,r.amount),rate:r.amount==null||r.status==='reference'?'—':s.rates.ratio(signed?r.amount:target<0n?-r.amount:r.amount,denom,true).replace(/^\+/,'' )})),records,note:'金额与费率共用相同构成；分类小计不重复计入合计，仅核对项目不计入金额和费率。分母为本行订单销售额，不扣退款。'+(sku?'子项按本行已分摊金额拆分，不是平台直接返回的SKU费用。':'')};
}
async function dispatch(request){const s=open(request),input=request.input;if(input.action==='table')return table(s,input);if(input.action==='table_detail')return detail(s,input);if(input.action==='history'){const rows=plain(s.c.LEDGER_FEES.history()).reverse(),size=20,page=input.page||1;return{rows:rows.slice((page-1)*size,page*size),total:rows.length,page};}throw Error('未知查询。');}
const rl=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
rl.on('line',line=>{try{const request=JSON.parse(line);Promise.resolve(dispatch(request)).then(result=>process.stdout.write(JSON.stringify({ok:true,result})+'\n'),error=>process.stdout.write(JSON.stringify({ok:false,error:error.message})+'\n'));}catch(error){process.stdout.write(JSON.stringify({ok:false,error:error.message})+'\n');}});
