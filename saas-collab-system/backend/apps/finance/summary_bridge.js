(function(){
 'use strict';
 const initial=__SAAS_FINANCE_BOOTSTRAP__,values={...initial.values};
 if(initial.toolsOnly)document.documentElement.classList.add('saas-settings-only');
 function context(){const table=document.getElementById('ledger-table'),fields=Object.fromEntries([...document.querySelectorAll('#filters input,#filters select')].map(e=>[e.id,e.value]));if(initial.toolsOnly){fields.store=document.getElementById('tool-shop')?.value||fields.store;fields.month=document.getElementById('tool-month')?.value||fields.month;}return{toolPanel:document.body.dataset.toolPanel,toolKind:document.getElementById('tool-kind')?.value,view:state.view,page:state.page,mode:globalThis.HTML2_STORE_HIERARCHY?.mode(),skuScope:document.getElementById('sku-scope')?.value,scrollLeft:table.scrollLeft,scrollTop:table.scrollTop,tabs:globalThis.HTML2_TAB_FILTERS?.memory?.(),fields};}
 function reasonFor(key,next){
  if(key==='html2-ledger-fees-v1')return next.history.at(-1)?.after?.reason;
  if(key==='html2-profit-closed-periods-v1')return Object.values(next).at(-1)?.reason;
  if(key==='html2-shopee-recharge-v1'){
   const old=JSON.parse(values[key]||'{}');
   if(JSON.stringify(next.audit?.at(-1))!==JSON.stringify(old.audit?.at(-1)))return next.audit?.at(-1)?.reason||'导入Shopee充值设置';
   const keys=[...new Set([...Object.keys(old.amortization||{}),...Object.keys(next.amortization||{})])].filter(k=>JSON.stringify(old.amortization?.[k])!==JSON.stringify(next.amortization?.[k]));
   return keys.length?next.amortization?.[keys[0]]?.reason||document.getElementById('ads-days-reason')?.value.trim()||'恢复自动估算周期':'导入Shopee充值设置（替换当前配置）';
  }
  if(key==='html2-lazada-tax-rules-v1')return next.at(-1)?.reason;
  if(key==='html2-lazada-amortization-v1')return document.getElementById('ads-days-reason')?.value.trim()||'恢复自动估算周期';
  return [...document.querySelectorAll('[data-fee-selection-reason]')].map(e=>e.value.trim()).find(Boolean)||Object.values(next).at(-1)?.reason||'恢复自动计算';
 }
 globalThis.SAAS_STORAGE={getItem:key=>values[key]||null,setItem(key,value){
  if(!initial.can_edit)throw Error('当前账号没有财务调整权限。');
  const next=JSON.parse(value);let submitted=value;
  if(key==='html2-profit-closed-periods-v1')submitted=JSON.stringify(Object.fromEntries(Object.entries(next).map(([month,book])=>[month,{reason:book.reason,adjustmentMonth:book.adjustmentMonth}])));
  const reason=reasonFor(key,next);values[key]=value;globalThis.SAAS_INVALIDATE();
  parent.postMessage({type:'finance-summary-write',dataset:initial.dataset,revision:initial.revision,key,value:submitted,reason,context:context()},'*');
 }};
 addEventListener('DOMContentLoaded',()=>{
  function viewport(height,top,visible){const style=document.documentElement.style;if(Number.isFinite(height)&&height>0)style.setProperty('--host-height',height+'px');if(Number.isFinite(top))style.setProperty('--dialog-top',top+'px');if(Number.isFinite(visible)&&visible>0)style.setProperty('--dialog-height',visible+'px');}
  viewport(initial.viewport_height);
  addEventListener('message',event=>{if(event.source===parent&&event.data?.type==='finance-summary-viewport'&&event.data.dataset===initial.dataset)viewport(event.data.height,event.data.top,event.data.visible);});
  function reportSize(){parent.postMessage({type:'finance-summary-size',dataset:initial.dataset,revision:initial.revision,height:document.body.getBoundingClientRect().height},'*');}
  new ResizeObserver(reportSize).observe(document.body);
  rawEntriesFor=SAAS_MEMO(rawEntriesFor);
  entriesFor=SAAS_MEMO(entriesFor);
  const quality=document.getElementById('quality-status'),fold=document.createElement('details');fold.id='saas-quality';
  const summary=document.createElement('summary');fold.append(summary);quality.before(fold);fold.append(quality);
  function presentation(){
   const t=document.querySelector('#ledger-table table'),band=t?.querySelector('.column-bands'),headers=t?.querySelector('thead tr:last-child');
   if(band&&headers&&!band.dataset.identitySplit){
    const first=band.firstElementChild,n=[...headers.children].filter(x=>x.classList.contains('frozen')).length;
    if(n&&n<first.colSpan){const rest=first.cloneNode(true);rest.colSpan=first.colSpan-n;rest.classList.remove('frozen-band');first.colSpan=n;first.after(rest);}
    band.dataset.identitySplit='true';
   }
   summary.textContent='数据范围与待核说明（'+quality.children.length+'项，点击展开）';fold.hidden=!quality.children.length;
   parent.postMessage({type:'finance-summary-context',dataset:initial.dataset,revision:initial.revision,context:context()},'*');
  }
  function scope(){
   const heading=document.querySelector('.scope-heading'),f=state.filters;
   const label=(id,value)=>[...document.getElementById(id).options].find(o=>o.value===String(value||''))?.textContent;
   heading.querySelector('strong').textContent='多平台财务汇总 · 已验收批次';
   heading.querySelector('.muted').textContent=[f.month||'全部账期',...['country','platform','store'].map(id=>f[id]?label(id,f[id]):null),'来源快照 · 未核对银行到账'].filter(Boolean).join(' · ');
  }
  let currentView=state.view;
  const priorRender=renderLedger;renderLedger=function(){const changed=currentView!==state.view;currentView=state.view;const result=priorRender.apply(this,arguments);if(changed){document.getElementById('ledger-table').scrollLeft=0;document.getElementById('ledger-table').scrollTop=0;}scope();presentation();return result;};
  globalThis.SAAS_READY=true;
  if(initial.toolsOnly){SAAS_SETUP_TOOLS(initial);return;}
  const table=document.getElementById('ledger-table');table.addEventListener('scroll',()=>parent.postMessage({type:'finance-summary-context',dataset:initial.dataset,revision:initial.revision,context:context()},'*'),{passive:true});
  const ctx=initial.context;if(!ctx){renderLedger();return;}
  globalThis.HTML2_TAB_FILTERS?.restoreMemory?.(ctx.tabs);
  if(ctx.mode)HTML2_STORE_HIERARCHY.setMode(ctx.mode);
  state.view=ctx.view||'store';renderLedger();
  const invalid=[];
  for(const [id,value]of Object.entries(ctx.fields||{})){const el=document.getElementById(id);if(el){el.value=value;if(value&&el.tagName==='SELECT'&&el.value!==value)invalid.push(({month:'账期',country:'国家',platform:'平台',store:'店铺',currency:'币种'})[id]||id);el.dispatchEvent(new Event('change',{bubbles:true}));}}
  if(ctx.skuScope)document.getElementById('sku-scope').value=ctx.skuScope;
  readFilters();state.page=ctx.page||1;renderLedger();
  if(invalid.length){const note=document.createElement('p');note.className='notice warn';note.textContent='原筛选条件已不适用，已清除：'+invalid.join('、');document.getElementById('filters').after(note);}
  requestAnimationFrame(()=>{table.scrollLeft=ctx.scrollLeft||0;table.scrollTop=ctx.scrollTop||0;});
 });
})();
