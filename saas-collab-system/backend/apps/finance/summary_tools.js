(function(){
 'use strict';
 // Reuse validated forms and handlers; the ledger is never shown in tool mode.
 globalThis.SAAS_SETUP_TOOLS=initial=>{
  const root=document.createElement('section');root.id='saas-settings-tools';
  root.innerHTML='<nav aria-label="账务设置功能" class="tabs"><button type="button" data-tool="advertising">广告设置</button><button type="button" data-tool="closing">关账</button></nav><form id="tool-scope"><label>账期<input id="tool-month" type="month" required></label><label>店铺<select id="tool-shop"></select></label><button type="button" id="tool-apply">查看</button></form><p id="tool-message" role="status"></p><div id="tool-content"></div>';
  document.body.append(root);
  const style=document.createElement('style');style.textContent=`
   .saas-settings-only main{display:none!important}
   .saas-settings-only body>:not(#saas-settings-tools):not(dialog):not(script):not(style){display:none!important}
   .saas-settings-only body{margin:0;background:white}
   #saas-settings-tools{padding:0 0 16px}
   #saas-settings-tools>.tabs{margin:0 0 16px}
   #saas-settings-tools>nav [aria-pressed=true]{background:#255ff2;color:white}
   #tool-scope{display:flex;gap:16px;flex-wrap:wrap;align-items:end;margin-bottom:16px}
   #tool-scope label{display:grid;gap:6px}
   #tool-content>dialog[open]{display:block;position:static!important;inset:auto!important;transform:none!important;margin:0;width:100%;max-width:none;height:auto!important;max-height:none!important;box-shadow:none;border:0;box-sizing:border-box;padding:0;overflow:visible}
   #tool-content>dialog>.drawer-head{display:none}
   #tool-content>dialog>.drawer-body{padding:8px 0 16px;overflow:visible}
   #tool-content>dialog>.tabs{position:static;padding:0}
   #tool-content>details{margin:0;border:0}
   #tool-content .mapping{max-width:100%}
   #tool-message:empty{display:none}
  `;document.head.append(style);
  const shops=LEDGER_FEES.shops(),fields=initial.context?.fields||{},month=document.getElementById('tool-month'),shop=document.getElementById('tool-shop'),content=document.getElementById('tool-content'),message=document.getElementById('tool-message');
  month.value=fields.month||[...new Set(HTML2_STORE_HIERARCHY.controls().map(f=>String(f.month||f.date||'').slice(0,7)).filter(m=>/^\d{4}-\d{2}$/.test(m)))].sort().reverse()[0]||'';
  for(const s of shops)shop.add(new Option(s.code,String(s.id)));
  const loadedStore=globalThis.SNAPSHOT?.database?.settings_store ?? (typeof SNAPSHOT==='object'?SNAPSHOT.database?.settings_store:undefined);
  if(loadedStore!=null)shop.value=String(loadedStore);
  else if(shops.some(s=>String(s.id)===String(fields.store)))shop.value=fields.store;
  else{const first=HTML2_STORE_HIERARCHY.controls().find(f=>f.store_id);if(first)shop.value=String(first.store_id);}
  const ad=document.getElementById('ads-settings-drawer'),closing=document.getElementById('profit-close-save').closest('details');
  for(const node of [ad,closing])content.append(node);
  let selected=initial.context?.toolPanel==='closing'?'closing':'advertising';
  let focusRecharge=initial.context?.toolKind==='recharge';
  function filters(){const s=shops.find(s=>String(s.id)===shop.value);globalThis.SAAS_CLOSING_SHOP=s?.code;state.view='store';state.page=1;state.filters={...state.filters,month:month.value,store:shop.value,country:s?.country||'',platform:'',currency:'',order:'',sku:''};for(const id of ['month','store','country','platform','currency','order','sku']){const el=document.getElementById(id);if(el)el.value=state.filters[id]||'';}}
  const render=renderLedger;
  function show(){
   if(loadedStore!=null&&String(loadedStore)!==shop.value){
    message.textContent='正在读取所选店铺的账务设置…';
    root.querySelectorAll('button,input,select,textarea').forEach(el=>{el.disabled=true;});
    parent.postMessage({type:'finance-summary-tool-scope',frame_id:initial.frame_id,dataset:initial.dataset,revision:initial.revision,context:{...initial.context,toolPanel:selected,fields:{...fields,store:shop.value,month:month.value}}},'*');return;
   }
   message.textContent='';filters();if(selected==='advertising')render();filters();
   document.body.dataset.toolPanel=selected;
   root.querySelectorAll('[data-tool]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tool===selected)));
   ad.removeAttribute('open');document.getElementById('drawer')?.removeAttribute('open');closing.hidden=true;
   if(selected==='advertising'){
    ad.setAttribute('open','');
    const code=shops.find(s=>String(s.id)===shop.value)?.code;
    for(const [id,value]of [['ads-rule-shop',code],['ads-rule-month',month.value]]){const el=document.getElementById(id);if(el&&value&&el.value!==value){el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));}}
    if(focusRecharge){focusRecharge=false;ad.querySelector('[data-ads-pane="rules"]')?.click();document.getElementById('ads-rule-principal')?.focus();}
   }
   else if(selected==='closing'){closing.hidden=false;closing.open=true;document.getElementById('profit-close-month').value=month.value;}
   if(!initial.can_edit)content.querySelectorAll('button,input,select,textarea').forEach(el=>{el.disabled=true;});
  }
  // Existing save handlers call renderLedger; retain the selected tool afterward.
  renderLedger=show;
  root.addEventListener('click',e=>{const button=e.target.closest('[data-tool]');if(button){selected=button.dataset.tool;show();}});
  document.getElementById('tool-apply').addEventListener('click',()=>{if(month.reportValidity())show();});
  document.getElementById('tool-scope').addEventListener('submit',e=>{e.preventDefault();show();});
  show();
 };
})();
