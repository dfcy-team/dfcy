// Read-only cost presentation. Monetary values come from the existing parent facts.
function costDetail(s,{entries,parts,target,partial,sales,input,level}){
 const {p}=s,quotes=new Map(),raw=new Map(),dates=new Set(),pendingOrders=new Set();
 const labels={normal:'正常订单',refund:'退货退款订单',cancelled_shipped:'出库但取消订单',sample:'样品订单',pending:'分类待核'};
 const groups=Object.fromEntries(Object.keys(labels).map(k=>[k,{orders:new Set(),pending:new Set(),cost:0n,credit:0n,costRows:0,creditRows:0,missing:0,receiptPending:0}]));
 const classificationPending=new Set();let crossMonthCount=0,crossMonthAmount=0n,categoryTotal=0n;
 let missingItems=0;
 const orders=entries.map((f,i)=>{
  const calc=f.cost_calculation||{},components=calc.components||[],reasons=[...new Set(calc.reasons||[])];
  const isReturn=f.cost_event==='return',included=f.status!=='reference';
  const classified=s.c?.HTML2_COST_COMPOSITION?.classify?.({...f,cost_calculation:calc});
  const category=Object.hasOwn(labels,classified)?classified:'pending',group=groups[category];
  const orderKey=[f.store_id,f.external_order_id||f.original_cost_id||f.source_id].join('|');
  const originalDate=f.original_cost_date||f.source_date||(f.accounting_adjustment?f.original_period:null)||(isReturn?null:f.date);
  const accountingDate=f.date||null;
  const crossMonth=!!(isReturn&&originalDate&&accountingDate&&String(originalDate).slice(0,7)!==String(accountingDate).slice(0,7));
  const verified=isReturn&&f.return_event?.verified===true&&!!f.return_event?.id&&!!f.return_event?.confirmed_at;
  const missing=components.filter(c=>c.unit_cost==null||c.local_amount==null||c.reasons?.length).length;
  const waiting=calc.state==='pending'||f.amount==null||f.status==='pending'||missing>0||isReturn&&!verified;
  if(included){
   group.orders.add(orderKey);if(category==='pending')classificationPending.add(orderKey);
   if(waiting)group.pending.add(orderKey);
   if(isReturn){group.creditRows++;if(!verified)group.receiptPending++;}
   else group.costRows++;
   if(f.amount==null)group.missing++;
   else{const value=p.micro(f.amount);group[isReturn?'credit':'cost']+=value;categoryTotal+=value;}
   if(crossMonth){crossMonthCount++;if(f.amount!=null)crossMonthAmount+=p.micro(f.amount);}
  }
  if(waiting)pendingOrders.add([f.store_id,f.external_order_id||f.source_id].join('|'));missingItems+=missing;
  if(calc.cost_at)dates.add(calc.cost_at);
  const conversion=f.cost_conversion,q=conversion?.quote;
  if(q)quotes.set([conversion.period,q.input_id,q.rate,conversion.from,conversion.to].join('|'),
   {period:conversion.period,from:conversion.from,to:conversion.to,rate:q.rate,input_id:q.input_id,
    source:q.source_description||q.source||'',source_hash:q.source_hash||''});
  const totals=new Map();
  for(const c of components)if(c.unit_cost!=null){
   const value=p.micro(c.net_cost);raw.set(c.currency,(raw.get(c.currency)||0n)+value);
   totals.set(c.currency,(totals.get(c.currency)||0n)+value);
  }
  return{key:String(f.cost_detail_key||f.ledger_key||f.source_id||i),date:f.date,shop:f.store_code,order:f.external_order_id||'店铺公共调整',
   event:isReturn?'商品成本回冲':f.accounting_adjustment?'商品成本调整':'商品成本',
   original_date:originalDate,accounting_date:accountingDate,cross_month:crossMonth,
   category,category_label:labels[category],included,
   classification_reason:calc.business_classification?.reason||'',
   classification_evidence:calc.business_classification?.evidence||null,
   relation:!included?'仅核对，不计入汇总':isReturn?
    (verified?'入库明细 #'+f.return_event.id:'已有回冲记录，入库核验依据待核')+
     '；'+(f.original_cost_id?'原成本 '+f.original_cost_id:'原成本关联待核'):
    (f.accounting_adjustment?'原期间 '+(f.original_period||'待核')+' 的后续调整':'沿用原成本归属日期'),
   amount:f.amount==null?null:p.fixed(p.micro(f.amount)),currency:f.currency,
   original:[...totals].map(([currency,amount])=>({currency,amount:p.fixed(amount)})),
   pending:waiting,missing_items:missing,reasons};
 });
 const definitions=[['normal','正常订单成本',false],['refund','退货退款订单商品成本',false],['refund','退货退款订单商品成本回冲',true],
  ['cancelled_shipped','出库但取消订单商品成本',false],['cancelled_shipped','出库但取消订单商品成本回冲',true],
  ['sample','样品商品成本',false],['sample','样品商品成本回冲',true],['pending','分类待核商品成本',false]];
 for(const key of ['normal','pending'])if(groups[key].creditRows)definitions.push([key,labels[key]+'商品成本回冲',true]);
 const categories=definitions.map(([key,label,credit])=>{
  const g=groups[key],count=g.orders.size,hasRows=credit?g.creditRows:g.costRows;
  return{key:key+(credit?':return':':cost'),label,order_count:count,
   amount:count&&hasRows?p.fixed(g[credit?'credit':'cost']):null,
   pending:g.pending.size>0||key==='pending',included:true,
   state:!count?'当前无已确认归属':credit&&!hasRows?'未核验入库，未计回冲':
    credit&&g.receiptPending?'已有回冲，入库核验依据待核':
    g.missing?'金额／汇率缺失，当前仅为已知部分':
    g.pending.size?'已知部分；'+g.pending.size+'单成本待核':
    key==='pending'?'订单分类依据待核':credit?'已有回冲按归属日期计入':'已知成本'};
 });
 if(target!=null&&categoryTotal!==target)categories.push({key:'difference',label:'来源待细分调整差额',order_count:0,amount:p.fixed(target-categoryTotal),pending:true,state:'与主表已知金额的差额，来源继续待核',included:true});
 const items=parts.filter(r=>r.included).map(r=>{
  const c=r.cost;
  return{key:r.key,sku:c?.sku||r.label,legacy:c?.legacy||'',quantity:c?.quantity??null,
   unit_cost:c?.unit_cost??null,original_amount:c&&(!c.original_missing||c.original_amount!==0n)?p.fixed(c.original_amount):null,
   original_partial:!!c?.original_missing,original_currency:c?.currency||'',
   amount:r.amount==null?null:p.fixed(r.amount),pending:r.amount==null||r.status==='pending',
   version_id:c?.version_id??null,version_no:c?.version_no??null,warehouse_id:c?.warehouse_id??null,
   effective_from:c?.effective_from||'',effective_to:c?.effective_to||'',
   reasons:c?.reasons?.length?c.reasons:r.amount==null&&c?.unit_cost!=null?['缺少折算汇率或已确认折算金额']:[],
   source:c?'':r.source||''};
 });
 const all=level==='orders'?orders:items,size=20,page=Math.min(input.cost_page||1,Math.max(1,Math.ceil(all.length/size)));
 const flowPage=Math.min(input.flow_page||1,Math.max(1,Math.ceil(orders.length/size)));
 const sorted=[...dates].sort(),known=target==null?null:p.fixed(target);
 return{title:level==='orders'?'商品成本 · 订单构成':'商品成本 · SKU构成',amount:known,
  sales:sales==null?null:p.fixed(sales),parts:[],records:[],
  note:'按结算日有效的已确认成本版本计算；按成本归属月份业务汇率折算。缺项继续待核，已知金额不代表成本完整。',
  cost:{level,currency:entries[0]?.currency||'',known_amount:known,partial:!!partial||pendingOrders.size>0,pending_orders:pendingOrders.size,missing_items:missingItems,
   order_count:new Set(entries.map(f=>[f.store_id,f.external_order_id||f.source_id].join('|'))).size,
   date_from:sorted[0]||'',date_to:sorted.at(-1)||'',quotes:[...quotes.values()],
   categories,category_total:known,classification_pending:classificationPending.size,
   cross_month_returns:{count:crossMonthCount,amount:p.fixed(crossMonthAmount)},
   flows:{rows:level==='orders'?[]:orders.slice((flowPage-1)*size,flowPage*size),page:flowPage,page_size:size,total:orders.length},
   original_totals:[...raw].map(([currency,amount])=>({currency,amount:p.fixed(amount)})),
   rows:all.slice((page-1)*size,page*size),page,page_size:size,total:all.length}};
}
module.exports={costDetail};
