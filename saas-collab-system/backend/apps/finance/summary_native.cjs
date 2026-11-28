// Read-only, version-scoped calculation process. No network and no posting APIs.
const readline=require('node:readline'),vm=require('node:vm'),fs=require('node:fs');
const {createEngine,plain}=require('./summary_engine.cjs'),sessions=new Map();
const {costDetail}=require('./summary_cost_detail.cjs');
const {orderLedger,itemMembers,groupMembers,groupLinks,orderAttribution,attributionTotals,itemAttribution}=require('./summary_order_ledger.cjs');
const {flowAmounts,flowInclusion,flowState,flowStatus,flowEditBlock}=require('./summary_flow_view.cjs');
const {periodOptions,periodRange,periodFilter,datedFact}=require('./summary_periods.cjs');
const feeKinds=['sales','refund','order_fee','adjustment','shop_adjustment','operations','finance','product_cost','gcash','promotion','warehouse_order','warehouse_other'];
const flowDate=f=>Object.hasOwn(f,'period_date')?f.period_date:Object.hasOwn(f,'statistics_date')?f.statistics_date:f.date;
function open(request,timings){
 if(sessions.has(request.key))return sessions.get(request.key);
 sessions.clear();
 const s=createEngine(request.path,request.input,{memo:true,timings,retainSource:false}),{c}=s,directoryStarted=performance.now();
 s.sourceScope=request.input.sourceScope;
 // Valid only for this immutable batch/settings session; never cache fee amounts.
 s.itemMatches=new Map();s.itemCostIndexes=new WeakMap();
 vm.runInContext(fs.readFileSync(__dirname+'/summary_runtime.js','utf8'),c);
 s.rates=c.HTML2_FEE_RATES;s.counted=vm.runInContext('countedFact',c);s.parts=vm.runInContext('ledgerParts',c);s.labels=vm.runInContext('KINDS',c);s.countries=vm.runInContext('COUNTRY',c);s.queries=new Map();s.ledgers=new Map();
 s.costFlows=vm.runInContext('SNAPSHOT.database?.cost_flows',c);
 s.rawFlows=vm.runInContext('SNAPSHOT.database?.raw_flows',c);
 s.labels.settlement='平台净结算';
 s.options=directoryOptions(s);
 timings.directory_ms=performance.now()-directoryStarted;
 sessions.set(request.key,s);return s;
}
function directoryOptions(s){
 const {c,p}=s,facts=p.entriesFor('store'),shops=new Map(),months=new Set(),dates=new Map(),calendar=!!(s.costFlows||s.rawFlows),missing=new Map();
 for(const f of facts){
  if(f.store_id)shops.set(String(f.store_id),{id:String(f.store_id),code:f.store_code,country:f.country,platform:f.platform,currency:p.displayCurrency(f)});
  const month=String(f.month||f.date).slice(0,7);if(!month)continue;months.add(month);
  if(!calendar){if(!dates.has(month))dates.set(month,[]);dates.get(month).push(datedFact(f,missing).period_date);}
 }
 for(const shop of c.LEDGER_FEES.shops())if(!shops.has(String(shop.id)))shops.set(String(shop.id),{...shop,id:String(shop.id),platform:shop.code.startsWith('LZ')?'lazada':'shopee'});
 const options={stores:[...shops.values()].sort((a,b)=>a.code.localeCompare(b.code)),countries:s.countries,kinds:c.LEDGER_FEES.kinds.map(k=>({key:k,label:s.labels[k]||k}))};
 options.editable_kinds=options.kinds;
 options.closed_periods=Object.entries(c.HTML2_PROFIT_RULES.closed()).map(([key,book])=>({shop:book.shop||'',month:book.month||key.slice(-7)}));
 if(s.costFlows)for(const f of s.costFlows)months.add(f.date.slice(0,7));
 if(s.rawFlows){
  options.raw_flows=true;options.kinds=[...new Set(s.rawFlows.map(f=>f.kind).concat(c.LEDGER_FEES.kinds))].map(key=>({key,label:s.labels[key]||key}));options.currencies=[...new Set(s.rawFlows.map(f=>f.original_currency||f.currency).concat(options.stores.map(f=>f.currency)))];
  for(const f of s.rawFlows)months.add(f.date.slice(0,7));
 }
 options.months=[...months].sort().reverse();
 options.periods_by_month=Object.fromEntries(options.months.map(month=>[month,periodOptions(month,calendar?[]:dates.get(month))]));
 return options;
}
const scopeMatches=(filters,f)=>!Array.isArray(filters._stores)||filters._stores.includes(String(f.store_id||''));
function scopedOptions(s,filters){
 if(!Array.isArray(filters._stores))return s.options;
 if(!s.scopedOptionCache)s.scopedOptionCache=new Map();
 const key=JSON.stringify([...new Set(filters._stores.map(String))].sort());
 if(s.scopedOptionCache.has(key)){const cached=s.scopedOptionCache.get(key);s.scopedOptionCache.delete(key);s.scopedOptionCache.set(key,cached);return cached;}
 const stores=s.options.stores.filter(shop=>filters._stores.includes(String(shop.id))),codes=new Set(stores.map(shop=>shop.code));
 const facts=s.p.entriesFor('store').concat(s.rawFlows||[],s.costFlows||[]).filter(f=>scopeMatches(filters,f));
 const months=[...new Set(facts.map(f=>String(f.month||f.date||'').slice(0,7)).filter(Boolean))].sort().reverse();
 const options={...s.options,stores,countries:Object.fromEntries(Object.entries(s.options.countries).filter(([key])=>stores.some(shop=>shop.country===key))),months,periods_by_month:Object.fromEntries(months.map(month=>[month,periodOptions(month)])),currencies:[...new Set(facts.map(f=>f.original_currency||f.currency).concat(stores.map(shop=>shop.currency)))],closed_periods:s.options.closed_periods.filter(book=>codes.has(book.shop))};
 if(s.scopedOptionCache.size>=8)s.scopedOptionCache.delete(s.scopedOptionCache.keys().next().value);
 s.scopedOptionCache.set(key,options);return options;
}
function query(s,view,filters,mode,scope='store'){
 const group=JSON.stringify([view,filters,scope]);
 if(s.queryGroup!==group){s.queries.clear();s.queryGroup=group;}
 const key=JSON.stringify([view,filters,mode,scope]);s.c.HTML2_STORE_HIERARCHY.setMode(mode);
 if(s.queries.has(key)){const rows=s.queries.get(key);s.queries.delete(key);s.queries.set(key,rows);return rows;}
 const rows=calculate(s,view,filters,mode,scope);s.queries.set(key,rows);return rows;
}
function calculate(s,view,filters,mode,scope='store'){
 const {c,p}=s,type=filters.period_type||'month',key=type+'|'+mode;c.HTML2_STORE_HIERARCHY.setMode(mode);
 const calendarWeek=type==='week'&&filters.period&&filters.period!=='undated';
 const within=periodFilter(type,filters.period),rowFilters={...filters,month:calendarWeek?'':filters.month,order:view==='sku'||view==='product_link'?'':filters.order,sku:''},localFilters={...filters,month:calendarWeek?'':filters.month,currency:'',sku:''};
 if(!s.ledgers.has(key)){if(s.ledgers.size>=2)s.ledgers.delete(s.ledgers.keys().next().value);s.ledgers.set(key,orderLedger(s,type,mode));}
 else{const ledger=s.ledgers.get(key);s.ledgers.delete(key);s.ledgers.set(key,ledger);}
 const pending=filters.attribution==='pending';
 let facts;
 if(view==='detail'&&!pending&&s.rawFlows){
  facts=s.rawFlows.concat(s.p.entriesFor('detail').filter(f=>f.ledger_added).map(f=>s.p.localFact(f))).filter(f=>scopeMatches(filters,f)&&(!filters.currency||filters.currency===(f.original_currency||f.currency))&&p.matches(f,localFilters)&&within(f));
 }else{
  const selected=s.ledgers.get(key).filter(f=>scopeMatches(filters,f)&&p.matches(f,rowFilters)&&within(f));
  facts=selected.filter(f=>pending?!!orderAttribution(s,f)&&!/^database:coverage:/.test(f.source_id||'')&&(f.amount==null||p.micro(f.amount)!==0n):!orderAttribution(s,f));
  if(view==='detail'&&!pending&&s.costFlows)facts=facts.filter(f=>f.kind!=='product_cost').concat(s.costFlows.filter(f=>scopeMatches(filters,f)&&(!filters.currency||filters.currency===f.currency)&&p.matches(f,localFilters)&&within(f)));
 }
 if(view==='detail'){
 const keyword=filters.keyword?.toLowerCase();
 return facts.filter(r=>{
  const day=flowDate(r);
  if((filters.from||filters.to)&&!/^\d{4}-\d{2}-\d{2}$/.test(day||'')||filters.from&&day<filters.from||filters.to&&day>filters.to||filters.kind&&r.kind!==filters.kind)return false;
  const sourceControl=(r.raw_source_flow||r.raw_cost_flow)&&(filters.status||filters.editable||keyword)?s.c.RAW_PARTICIPATION.info(r.source_id):null;
  if(keyword){const text=[sourceControl?.change?.reason,r.source,r.description,r.allocation_reason,r.statistics_date_reason,...(r.ledger_original?.rows||r.rows||[]).map(x=>x.name)].join(' ').toLowerCase();if(!text.includes(keyword))return false;}
  if(filters.editable||filters.status==='readonly'){
   const can=!flowEditBlock(s,r)&&(!!sourceControl?.supported||!r.allocation_readonly&&c.LEDGER_FEES.editable(r)&&(r.kind==='advertising'||r.amount!=null)&&!!r.ledger_key);
   if(filters.editable&&!can||filters.status==='readonly'&&can)return false;
  }
  if(filters.status&&filters.status!=='readonly'){
   const sourceStatus=sourceControl?.excluded||r.ledger_disabled?'disabled':r.ledger_added?'added':r.ledger_adjusted?'modified':r.status==='pending'||r.amount==null||r.statistics_date_reason||!day?'pending':'normal';
   const status=['normal','pending'].includes(filters.status)&&(r.raw_source_flow||r.raw_cost_flow)?flowState(s,r,sourceControl):sourceStatus;
   if(status!==filters.status)return false;
  }
  return true;
 }).sort((a,b)=>String(flowDate(b)||b.month).localeCompare(String(flowDate(a)||a.month)));
 }
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
 if(entries.length&&entries.every(f=>f.amount==null||kind==='product_cost'&&f.cost_calculation?.components?.length&&f.cost_calculation.components.every(c=>Object.hasOwn(c,'unit_cost')&&c.unit_cost==null||c.reasons?.length)))return{amount:0n,partial:true};
 return value.partial&&value.amount==null?{amount:0n,partial:true}:value;
}
function summaryRatio(s,value,sales){
 value=s.rates.displayAmount(value);sales=s.rates.displayAmount(sales);
 if(value==null||sales==null)return '—';
 if(sales===0n)return '0.00%';
 const numerator=value<0n?-value:value,denominator=sales<0n?-sales:sales,basis=(numerator*10000n+denominator/2n)/denominator;
 return(basis&&((value<0n)!==(sales<0n))?'-':'')+(basis/100n)+'.'+String(basis%100n).padStart(2,'0')+'%';
}
function fieldIssues(s,g,kind,sku){
 const entries=sku?(g?.members||g?.skus?.flatMap(x=>x.members)||[]).map(m=>m.fact).filter(f=>f?.kind===kind):g?.cells[kind]?.entries||[],reasons=new Set();
 for(const f of entries){
  const components=f.cost_calculation?.components||[];
  if(f.status==='reference'||f.ledger_disabled)continue;
  if(f.amount==null||f.status==='pending'||f.fx_pending||f.cost_calculation?.state==='pending')reasons.add(f.description||f.allocation_reason||(f.fx_pending?'原币折算汇率缺失':'来源金额或核算依据未完整获取'));
  for(const component of components)for(const reason of component.reasons||[])reasons.add(String(reason));
  if(f.statistics_date_reason)reasons.add(f.statistics_date_reason);
 }
 if(!reasons.size&&s.rates.read(g,kind,sku).partial)reasons.add((s.labels[kind]||kind)+'来源或汇率不完整，当前为已知部分');
 if(!reasons.size&&s.rates.read(g,kind,sku).amount==null)reasons.add((s.labels[kind]||kind)+'未取得金额依据，尚不能认定为零；其他已知字段继续独立计算');
 return [...reasons].slice(0,8);
}
function amount(s,value){return value==null?null:s.p.fixed(value);}
function summaryTotals(s,groups,operations,finance,sku){
 const totals=new Map();
 for(const [i,g]of groups.entries()){
  const key=rowKey(g,i),currency=g.currency;if(!totals.has(currency))totals.set(currency,{currency,sales:0n,operations:0n,finance:0n,partial:false});
  const row=totals.get(currency),sales=cell(s,g,'sales',sku),cost=cell(s,g,'product_cost',sku),op=s.rates.profit(operations.get(key),sku),fin=s.rates.profit(finance.get(key),sku);
  row.sales+=sales.amount||0n;row.operations+=op||0n;row.finance+=fin||0n;row.partial ||= !!g.pending||sales.partial||cost.partial||sales.amount==null||op==null||fin==null||feeKinds.some(kind=>{const group=kind==='operations'?operations.get(key):kind==='finance'?finance.get(key):g,r=cell(s,group,['operations','finance'].includes(kind)?'advertising':kind,sku);return r.partial||r.amount==null;});
 }
 return [...totals.values()].map(row=>({...row,sales:amount(s,row.sales),operations:amount(s,row.operations),finance:amount(s,row.finance)}));
}
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function factHtml(s,f,filters={}){
 if(Array.isArray(filters._stores))return '<h3>授权店铺的金额来源</h3><p>店铺：'+esc(f.store_code)+'；订单：'+esc(f.external_order_id||'店铺公共费用')+'；日期：'+esc(flowDate(f)||'待归期')+'</p><p>来源编号：'+esc(f.source_id)+'；金额：'+esc(f.amount??'待核')+' '+esc(f.currency)+'</p><p>仅返回授权店铺的记录；完整原始文件与跨店费用池依据不在此入口返回。</p>';
 if(f.raw_source_flow||f.raw_cost_flow){const converted=flowAmounts(s,f),c=converted.conversion;return '<h3>原始记录依据</h3><p>'+esc(f.description||f.source)+'</p><p>来源编号：'+esc(f.source_id)+'；业务日期：'+esc(f.date)+'；金额：'+esc(f.amount==null?'待核':f.amount)+' '+esc(f.currency)+'</p><p>'+esc(f.period_date_basis||'原始记录业务日期')+'</p><h3>金额折算依据</h3><p>原币：'+esc(converted.original_amount??'待核')+' '+esc(converted.original_currency)+'；折算：'+esc(converted.amount??'待核')+' '+esc(converted.currency)+'；汇率：'+esc(c.rate??'待核')+'；'+esc(c.basis)+'；'+esc(c.period)+(c.input_id?'；依据 #'+esc(c.input_id):'')+'</p><pre>'+esc(JSON.stringify(f.source_proof||{},null,2))+'</pre>';}
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
 if(!s.tableStats)s.tableStats=new Map();
 const statsKey=JSON.stringify([view,filters,mode,scope]);
 if(!s.tableStats.has(statsKey)){if(s.tableStats.size>=4)s.tableStats.delete(s.tableStats.keys().next().value);s.tableStats.set(statsKey,{});}
 const stats=s.tableStats.get(statsKey);
 s.tableStats.delete(statsKey);s.tableStats.set(statsKey,stats);
 const ops=query(s,view,filters,view==='detail'?mode:'operations',scope),fin=view==='detail'?[]:query(s,view,filters,'finance',scope),opMap=view==='detail'?null:new Map(ops.map((g,i)=>[rowKey(g,i),g])),finMap=view==='detail'?null:new Map(fin.map((g,i)=>[rowKey(g,i),g]));
 const base=view==='detail'?ops:[...new Map((mode==='finance'?fin.concat(ops):ops.concat(fin)).map((g,i)=>[rowKey(g,i),g])).values()];
 if(!stats.summary_totals){
 if(view==='detail'){
  const scopeFilters=Object.fromEntries(['_stores','month','period_type','period','country','platform','store','currency'].map(k=>[k,k==='currency'&&s.rawFlows?'':filters[k]||''])),a=query(s,'store',scopeFilters,'operations'),b=query(s,'store',scopeFilters,'finance');
  stats.summary_totals=summaryTotals(s,[...new Map(a.concat(b).map((g,i)=>[rowKey(g,i),g])).values()],new Map(a.map((g,i)=>[rowKey(g,i),g])),new Map(b.map((g,i)=>[rowKey(g,i),g])),false);
 }else stats.summary_totals=summaryTotals(s,base,opMap,finMap,sku);
 }
 const summary_totals=stats.summary_totals;
 const current=Math.min(page,Math.max(1,Math.ceil(base.length/page_size))),rows=base.slice((current-1)*page_size,current*page_size).map((g,i)=>{
  const key=rowKey(g,(current-1)*page_size+i);if(view==='detail'){
   const participation=(g.raw_source_flow||g.raw_cost_flow)?s.c.RAW_PARTICIPATION.info(g.source_id):null,can=!flowEditBlock(s,g)&&!g.allocation_readonly&&s.c.LEDGER_FEES.editable(g)&&(g.kind==='advertising'||g.amount!=null)&&!!g.ledger_key;
   const attribution=g.raw_cost_flow||g.raw_source_flow?'':orderAttribution(s,g),converted=flowAmounts(s,g),inclusion=g.raw_source_flow||g.raw_cost_flow?flowInclusion(s,g,participation):null;
   return{key,edit_block_reason:flowEditBlock(s,g),participation:participation?{supported:participation.supported,excluded:participation.excluded,reason:participation.reason}:null,edit_key:g.ledger_key,identity:{country:s.countries[g.country]||g.country,store:String(g.store_id||''),shop:g.store_code||'国家公共费用',currency:converted.currency,order:g.external_order_id||''},date:flowDate(g)||'待归期',date_basis:g.period_date_basis||g.statistics_date_basis||'',accounting_date:g.date,accounting_month:String(g.month||g.date).slice(0,7),source_bill_month:g.source_bill_month,date_reason:g.statistics_date_reason||'',kind:g.kind,label:s.labels[g.kind]||g.kind,mode:g.ledger_ad_mode||g.ledger_record?.mode||'both',mode_label:inclusion?.mode_label,conversion:converted.conversion,amount:converted.amount,original_amount:converted.original_amount,original_currency:converted.original_currency,source_id:g.source_id,flow_type:g.source_proof?.transaction_type||g.source_proof?.type||s.labels[g.kind]||g.kind,status:flowStatus(g,inclusion,converted.conversion)||(participation?.excluded?'已排除（原额保留）':g.ledger_disabled?'已禁用':g.status==='reference'?'仅核对，不计入':attribution?'待归属订单（不计入正式汇总）':g.ledger_added?'新增费用':g.ledger_adjusted?'已修改':g.status==='pending'||g.amount==null?'待核／缺汇率':!flowDate(g)?'待归期':g.allocation_readonly?'规则分摊（只读）':'正常'),source:g.source,description:[inclusion?.reason,participation?.change?.reason,attribution,g.description,g.allocation_reason,g.period_date_basis,g.statistics_date_reason].filter(Boolean).join('；'),editable:can,added:!!g.ledger_added,disabled:!!g.ledger_disabled,record:g.ledger_record||null};
  }
  const operation=opMap.get(key),finance=finMap.get(key),values={},partial={},field_issues={};
  for(const kind of feeKinds){const isAd=['operations','finance'].includes(kind),group=isAd?(kind==='operations'?operation:finance):g,sourceKind=isAd?'advertising':kind,r=cell(s,group,sourceKind,sku);values[kind]=amount(s,r.amount);partial[kind]=r.partial;field_issues[kind]=fieldIssues(s,group,sourceKind,sku);if(boundary)field_issues[kind].push('本周期超出已接入日期范围，当前仅为已载入部分');}
  const profits={operations:s.rates.profit(operation,sku),finance:s.rates.profit(finance,sku)},sales=cell(s,g,'sales',sku),cost=cell(s,g,'product_cost',sku),denominator=sales.amount,rates={};
  const labeledIssues=keys=>[...new Set(keys.flatMap(k=>field_issues[k].map(reason=>(s.labels[k]||k)+'：'+reason)))];
  field_issues.gross_margin=labeledIssues(['sales','product_cost']);
  for(const mode of ['operations','finance'])field_issues['profit_'+mode]=labeledIssues(feeKinds.filter(k=>!['operations','finance'].includes(k)||k===mode));
  for(const [kind]of s.rates.fields)rates[kind]=summaryRatio(s,kind==='gross_margin'?sales.amount==null?null:s.rates.displayAmount(sales.amount)+s.rates.displayAmount(cost.amount||0n):kind.startsWith('profit_')?profits[kind.slice(7)]:values[kind]==null?null:s.p.micro(values[kind]),denominator);
  for(const kind of feeKinds)if(!Object.hasOwn(rates,kind))rates[kind]=summaryRatio(s,values[kind]==null?null:s.p.micro(values[kind]),denominator);
  const compositions={};
  for(const kind of [...feeKinds,'gross_margin','profit_operations','profit_finance','rate:product_cost'])compositions[kind]=detail(s,{...input,row_key:key,kind,source_key:undefined,cost_page:1,flow_page:1,composition_only:true},{operations:opMap,finance:finMap});
  return{key,identity:identity(s,g,view),values,partial,field_issues,compositions,profits:{operations:amount(s,profits.operations),finance:amount(s,profits.finance)},rates,pending:boundary||!!g.pending||Object.values(values).some(x=>x==null)||Object.values(partial).some(Boolean)};
 });
 if(!stats.attribution){
 stats.undated=query(s,'detail',{...filters,from:'',to:'',kind:'warehouse_order',status:'',keyword:'',editable:''},mode).filter(f=>f.statistics_date_reason).length;
 const totals=[];let itemGaps=[];
 const common=Object.fromEntries(['_stores','month','country','platform','store','currency'].map(k=>[k,filters[k]||'']));
 if(filters.period_type==='week'&&range)common.month='';
 if(!s.attributionReports)s.attributionReports=new Map();
 for(const basis of ['operations','finance']){
  const type=filters.period_type||'month',key=JSON.stringify([basis,type,filters.period,common]);
  if(!s.attributionReports.has(key)){
   s.c.HTML2_STORE_HIERARCHY.setMode(basis);
   const ledger=s.ledgers.get(type+'|'+basis)||orderLedger(s,type,basis),within=periodFilter(type,filters.period),facts=ledger.filter(f=>scopeMatches(filters,f)&&s.p.matches(f,common)&&within(f));
   if(s.attributionReports.size>=4)s.attributionReports.delete(s.attributionReports.keys().next().value);
   s.attributionReports.set(key,{totals:attributionTotals(s,facts),item_gaps:itemAttribution(s,facts.filter(f=>!orderAttribution(s,f)),ledger)});
  }
  const report=s.attributionReports.get(key);
  s.attributionReports.delete(key);s.attributionReports.set(key,report);
  totals.push(...report.totals.filter(g=>g.total!=='0.000000'||g.pending_rows||g.unknown_rows).map(g=>({...g,mode:basis,label:s.labels[g.kind]||g.kind,country:s.countries[g.country]||g.country})));
  if(basis===mode)itemGaps=report.item_gaps;
 }
 stats.attribution={totals,item_gaps:itemGaps,pending_rows:totals.filter(g=>g.mode===mode).reduce((n,g)=>n+g.pending_rows,0)};
 }
 const attribution=stats.attribution,itemGaps=attribution.item_gaps,undated=stats.undated;
 if(view!=='detail')for(const row of rows)if(itemGaps.some(g=>row.identity.shop===g.store||view==='country'&&s.options.stores.some(shop=>shop.code===g.store&&s.countries[shop.country]===row.identity.country)))row.pending=true;
 return{view,mode,rows,total:base.length,page:current,page_size,summary_totals,options:scopedOptions(s,filters),labels:s.labels,rate_fields:s.rates.fields,attribution,allocation_version:'order-ledger-v3',period_warning:boundary?`本周期超出已接入范围（${s.sourceScope.from} — ${s.sourceScope.to}），仅计算已载入部分，不认定完整周期；未自动补采数据。`:'',period_note:'正式汇总共用已归属订单明细。未关联／未分摊的仓库处理费及仓库其他费不参与本次汇总，也不进入待核对；原登记保留不动。无订单的订单调整、公共订单费用及店铺调整按同店同币种所选月／自然周／半月的有效结算销售额分摊，直接关联订单的调整不重摊。其他来源确实缺金额、日期或同期分母时才保留待核对；订单内缺商品依据仍明确标记。已关联仓库费用、成本及汇率规则不变。',date_warning:undated?`${undated}笔已关联出库处理费缺少唯一发货／揽收日期，金额保留在原账期及待归期，不混入未关联费用待核对区。已关联仓库其他费沿用对应订单归期。`:''};
}
function detail(s,input,groups){
 const {view,filters={},scope='store',mode='operations',row_key,kind}=input,sku=['sku','product_link'].includes(view),g=groups?groups[mode]?.get(row_key):query(s,view,filters,mode,scope).find((x,i)=>rowKey(x,i)===row_key);
 if(!g)throw Error('该行已变化，请刷新后重试。');
 if(groups)s.c.HTML2_STORE_HIERARCHY.setMode(mode);
 if(view==='detail')return{title:(s.labels[g.kind]||g.kind)+' · 来源及核算依据',html:factHtml(s,g,filters),records:[]};
 const isRate=kind.startsWith('rate:'),k=isRate?kind.slice(5):kind,ad=['operations','finance'].includes(k),targetKind=ad?'advertising':k;
 if(ad&&mode!==k)return detail(s,{...input,mode:k},groups);
 if(k.startsWith('profit_')&&mode!==k.slice(7))return detail(s,{...input,mode:k.slice(7)},groups);
 const read=cell(s,g,targetKind,sku),sales=cell(s,g,'sales',sku),cost=cell(s,g,'product_cost',sku),net=k.startsWith('profit_'),gross=k==='gross_margin',target=gross?(sales.amount==null||cost.amount==null?null:s.rates.displayAmount(sales.amount)+s.rates.displayAmount(cost.amount)):net?s.rates.profit(g,sku):read.amount;
 if(k==='product_cost'&&!isRate){
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
 let parts=[],records=[],recordsTotal=0,recordsPage=1;const recordsSize=50;
 function sourceRecords(items,record){
  if(input.composition_only){recordsTotal=items.length;return [];}
  if(!input.flow_page)return items.map(record);
  recordsTotal=items.length;recordsPage=Math.max(1,Math.min(input.flow_page,Math.max(1,Math.ceil(recordsTotal/recordsSize))));
  const offset=(recordsPage-1)*recordsSize;return items.slice(offset,offset+recordsSize).map((item,index)=>record(item,offset+index));
 }
 if(gross)parts=[{label:'订单销售额',amount:sales.amount},{label:'商品净成本',amount:cost.amount}];
 else if(net)parts=Object.keys(sku?g.amounts:g.cells).map(key=>({label:s.labels[key]||key,amount:cell(s,g,key,sku).amount}));
 else if(sku){
  const members=(g.members||g.skus?.flatMap(part=>part.members)||[]).filter(m=>Object.hasOwn(m.amounts,targetKind));
  if(input.source_key){const m=members[Number(String(input.source_key).replace(/^member:/,''))];if(!m||!String(input.source_key).startsWith('member:'))throw Error('来源记录已变化，请重新打开。');return{title:'订单到当前SKU／链接的费用份额',html:factHtml(s,m.fact,filters)+'<p>订单核算金额：'+esc(m.fact.amount)+'；当前份额：'+esc(m.amounts[targetKind]==null?'待核':s.p.fixed(m.amounts[targetKind]))+' '+esc(g.currency)+'；'+esc(m.hierarchy_basis)+'</p>',records:[]};}
  records=isRate?[]:sourceRecords(members,(m,i)=>({key:'member:'+i,date:flowDate(m.fact)||'待归期',shop:m.shop,order:m.fact.external_order_id,source:m.fact.source,description:m.hierarchy_basis,amount:m.amounts[targetKind]==null?null:s.p.fixed(m.amounts[targetKind]),currency:m.currency}));
  const data={sku:true,group:g,[k]:g,fees:{[k]:{amount:target}}};parts=s.c.FINANCE_COMPOSITION.build(data,k);
 }
 else{
  const entries=g.cells[targetKind]?.entries||[];
  if(input.source_key){const f=entries.find((f,i)=>String(f.allocation_key||f.ledger_key||f.source_id||i)===input.source_key);if(!f)throw Error('来源记录已变化，请重新打开。');return{title:'原始金额来源',html:factHtml(s,f,filters),records:[]};}
  records=isRate?[]:sourceRecords(entries,(f,i)=>({key:String(f.allocation_key||f.ledger_key||f.source_id||i),date:flowDate(f)||'待归期',shop:f.store_code,order:f.external_order_id,source:f.source,description:[f.description,f.allocation_reason,f.period_date_basis].filter(Boolean).join('；'),amount:f.amount,currency:f.currency}));
  parts=s.c.FINANCE_COMPOSITION.fromEntries(entries,target);
 }
 const rounded=parts.map(r=>({...r,amount:s.rates.displayAmount(r.amount)})),total=s.rates.displayAmount(target),sum=rounded.filter(r=>r.included!==false).reduce((n,r)=>n+(r.amount||0n),0n);
 if(total!=null&&sum!==total)rounded.push({label:'显示精度／来源待细分差额',amount:total-sum});
 const denom=sales.amount;
 return{title:(isRate?s.rates.fields.find(x=>x[0]===k)?.[1]:s.labels[targetKind]||k)+' · 构成',amount:amount(s,total),sales:amount(s,denom),rate:summaryRatio(s,total,denom),parts:rounded.map(r=>({label:r.label,level:r.level||2,subtotal:r.leaf===false,included:r.included!==false,status:r.status,source:r.source||'',amount:amount(s,r.amount),rate:r.amount==null||r.status==='reference'?'—':summaryRatio(s,r.amount,denom)})),records,...(input.flow_page?{records_total:recordsTotal,records_page:recordsPage,records_page_size:recordsSize}:{}),note:'金额与费率共用相同构成；分类小计不重复计入合计，仅核对项目不计入金额和费率。分母为本行订单销售额，不扣退款。'+(sku?'子项按本行已分摊金额拆分，不是平台直接返回的SKU费用。':'')};
}
async function dispatch(request,timings){
 const started=performance.now(),s=open(request,timings),input=request.input;
 timings.open_ms=performance.now()-started;
 const calculateStarted=performance.now();
 try{
 if(input.action==='table')return table(s,input);if(input.action==='table_detail')return detail(s,input);if(input.action==='history'){const rows=plain(s.c.LEDGER_FEES.history().concat(s.c.RAW_PARTICIPATION.state().history)).filter(row=>{const ids=input.filters?._stores;if(!Array.isArray(ids))return true;const stores=[row.before?.store,row.after?.store].filter(v=>v!=null);return stores.length>0&&stores.every(id=>ids.includes(String(id)));}).sort((a,b)=>b.at.localeCompare(a.at)),size=20,page=input.page||1;return{rows:rows.slice((page-1)*size,page*size),total:rows.length,page};}throw Error('未知查询。');
 }finally{timings.calculate_ms=performance.now()-calculateStarted;}
}
module.exports={summaryRatio,fieldIssues,summaryTotals,scopeMatches,scopedOptions,directoryOptions,query,calculate,table,detail};
if(require.main===module){
const rl=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
rl.on('line',line=>{try{const request=JSON.parse(line),timings={};Promise.resolve(dispatch(request,timings)).then(result=>process.stdout.write(JSON.stringify({ok:true,result,timings})+'\n'),error=>process.stdout.write(JSON.stringify({ok:false,error:error.message})+'\n'));}catch(error){process.stdout.write(JSON.stringify({ok:false,error:error.message})+'\n');}});
}
