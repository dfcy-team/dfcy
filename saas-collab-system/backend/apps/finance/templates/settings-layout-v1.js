(function(){
 'use strict';
 if(typeof document==='undefined'||!globalThis.SHOPEE_RECHARGE)return;
 const rules=document.getElementById('shopee-recharge-panel'),amortization=document.getElementById('advertising-amortization-settings');
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const money=n=>Number(n)/100;
 const format=n=>money(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
 document.body.classList.add('html2-clean');document.title='财务汇总 · HTML2';
 document.querySelector('main header h1').textContent='财务汇总';
 document.querySelector('main header .crumb').textContent='财务中心 / 结算月汇总';
 document.querySelector('main header .intro').textContent='按结算月查看经营收支，点击金额追溯构成与来源。';
 const drawer=document.createElement('dialog');drawer.id='ads-settings-drawer';drawer.setAttribute('aria-labelledby','ads-settings-title');
 drawer.innerHTML='<div class="drawer-head"><div><h2 id="ads-settings-title">广告设置</h2><p class="caption">Shopee · 规则按店铺独立保存 · 仅当前浏览器生效</p></div><button type="button" id="ads-settings-close" aria-label="关闭广告设置">关闭</button></div><nav class="tabs" aria-label="广告设置栏目"><button type="button" data-ads-pane="rules" aria-pressed="true">充值规则与确认</button><button type="button" data-ads-pane="amortization" aria-pressed="false">摊销与计算依据</button></nav><div class="drawer-body"><section id="ads-rules-pane" aria-label="充值规则与确认"></section><section id="ads-amortization-pane" aria-label="摊销与计算依据" hidden></section></div>';
 document.body.append(drawer);document.getElementById('ads-rules-pane').append(rules);document.getElementById('ads-amortization-pane').append(amortization);rules.open=amortization.open=true;
 const rulePane=document.getElementById('ads-rules-pane'),allShops=SHOPEE_RECHARGE.data.shops.concat(globalThis.HTML2_LAZADA_FINANCE?.shops||[]);
 const common=document.createElement('section');common.id='advertising-rule-form';
 common.innerHTML='<p class="caption">SP与LZ共用此表单。本金按到账金额填写，税率人工设置；本金加税额须匹配原扣款。规则仅在当前浏览器保存。</p><div class="ads-rule-form"><label>店铺<select id="ads-rule-shop">'+allShops.map(s=>'<option value="'+esc(s.code)+'">'+esc(s.code)+' · '+s.currency+'</option>').join('')+'</select></label><label>交易月份<input id="ads-rule-month" type="month"></label><label>目标账户<select id="ads-rule-channel"><option value="inside">站内广告余额</option><option value="outside">站外广告共用余额</option></select></label><label>到账本金 <span id="ads-rule-currency"></span><input id="ads-rule-principal" inputmode="decimal"></label><label>税率（%）<input id="ads-rule-rate" inputmode="decimal"></label><label>生效日期<input id="ads-rule-from" type="date"></label><label>结束日期（可空）<input id="ads-rule-to" type="date"></label><label>设置原因<input id="ads-rule-reason" maxlength="500"></label><button type="button" id="ads-rule-save">保存新版本</button><button type="button" id="ads-rule-cancel" hidden>取消修改</button></div><p id="ads-rule-message" role="status"></p>';
 rulePane.prepend(common);const lzHistory=document.createElement('section');lzHistory.id='lazada-tax-settings';rulePane.append(lzHistory);
 let ruleEdit=null,lastScope=null;
 const ruleValue=key=>document.getElementById('ads-rule-'+key).value;
 function resetRule(){ruleEdit=null;for(const key of ['principal','rate','to','reason'])document.getElementById('ads-rule-'+key).value='';document.getElementById('ads-rule-from').value=ruleValue('month')+'-01';document.getElementById('ads-rule-save').textContent='保存新版本';document.getElementById('ads-rule-cancel').hidden=true;}
 function syncRuleForm(){
  const code=ruleValue('shop'),lz=code.startsWith('LZ'),shop=allShops.find(s=>s.code===code),option=document.querySelector('#ads-rule-channel option[value="outside"]');
  option.hidden=option.disabled=/^(LZ|SPKJ)/.test(code);if(option.disabled)document.getElementById('ads-rule-channel').value='inside';
  document.getElementById('ads-rule-currency').textContent=shop?.currency||'';rules.hidden=lz;lzHistory.hidden=!lz;rules.querySelector('summary').hidden=true;
  const principal=document.getElementById('ads-rule-principal');principal.disabled=lz;principal.closest('label').hidden=lz;
  common.querySelector('.caption').textContent=lz?'LZ仅设置站内充值税率和生效期间。充值金额取账户流水含税扣款；税额＝扣款×税率÷（1＋税率），逐笔保留两位小数。无需填写到账本金。':'SP按到账本金及人工税率匹配原扣款。规则按店铺独立保存，仅当前浏览器生效。';
  if(lz)lzHistory.innerHTML='<div class="table-wrap"><table><thead><tr><th>账户／版本</th><th>税率</th><th>生效期间</th><th>原因</th><th>操作</th></tr></thead><tbody>'+HTML2_LAZADA_FINANCE.taxRules().filter(r=>r.shop===code).map(r=>'<tr><td>站内广告余额 / v'+r.version+'</td><td>'+esc(r.rate)+'%</td><td>'+esc(r.from)+' ～ '+esc(r.to||'持续')+'</td><td>'+esc(r.reason)+'</td><td><button type="button" data-lz-rule-edit="'+r.version+'">修改</button></td></tr>').join('')+'</tbody></table></div>';
  else for(const [id,value]of [['recharge-shop',code],['recharge-month',ruleValue('month')]]){const select=document.getElementById(id);if(select.value!==value){select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}));}}
 }
 common.addEventListener('change',e=>{if(['ads-rule-shop','ads-rule-month'].includes(e.target.id)){resetRule();syncRuleForm();tidyRules();}});
 common.addEventListener('click',e=>{
  if(e.target.id==='ads-rule-cancel'){resetRule();return;}if(e.target.id!=='ads-rule-save')return;
  try{const input={shop:ruleValue('shop'),channel:ruleValue('channel'),principal:ruleValue('principal'),rate:ruleValue('rate'),from:ruleValue('from'),to:ruleValue('to'),reason:ruleValue('reason')};
   if(input.shop.startsWith('LZ')){delete input.principal;HTML2_LAZADA_FINANCE.addTaxRule(input);}else if(ruleEdit)SHOPEE_RECHARGE.editRule(ruleEdit,input);else SHOPEE_RECHARGE.addRule(input);
   if(!input.shop.startsWith('LZ'))document.getElementById('recharge-shop').dispatchEvent(new Event('change',{bubbles:true}));
   resetRule();renderLedger();document.getElementById('ads-rule-message').textContent='已保存，广告费用已更新；仅当前浏览器生效。';
  }catch(error){document.getElementById('ads-rule-message').textContent=error.message;}
 });
 rulePane.addEventListener('click',e=>{const target=e.target.closest('[data-recharge-edit],[data-lz-rule-edit]');if(!target)return;
  const r=target.dataset.lzRuleEdit?HTML2_LAZADA_FINANCE.taxRules().find(r=>String(r.version)===target.dataset.lzRuleEdit):SHOPEE_RECHARGE.state().rules.find(r=>r.id===target.dataset.rechargeEdit);if(!r)return;
  ruleEdit=r.id||'lz:'+r.version;for(const [key,value]of Object.entries({shop:r.shop,channel:r.channel||'inside',principal:r.principal||'',rate:r.rate,from:r.from,to:r.to||'',reason:r.reason}))document.getElementById('ads-rule-'+key).value=value;
  document.getElementById('ads-rule-save').textContent='保存修改';document.getElementById('ads-rule-cancel').hidden=false;document.getElementById(r.shop.startsWith('LZ')?'ads-rule-rate':'ads-rule-principal').focus();
 });
 const actions=document.createElement('div');actions.className='finance-actions';
 const button=document.createElement('button');button.id='open-ads-settings';button.type='button';button.textContent='广告设置';button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-controls',drawer.id);
 document.getElementById('ledger-count').before(actions);actions.append(document.getElementById('ledger-count'),button);
 let lastTrigger=button;
 button.addEventListener('click',()=>{lastTrigger=button;const shop=SHOPEE_RECHARGE.data.shops.find(s=>String(s.id)===state.filters.store),select=document.getElementById('recharge-shop');if(shop&&select.value!==shop.code){select.value=shop.code;select.dispatchEvent(new Event('change',{bubbles:true}));}const month=document.getElementById('recharge-month');if(state.filters.month&&month.value!==state.filters.month){month.value=state.filters.month;month.dispatchEvent(new Event('change',{bubbles:true}));}drawer.showModal();});
 document.getElementById('ads-settings-close').addEventListener('click',()=>drawer.close());
 drawer.addEventListener('close',()=>lastTrigger.focus());
 drawer.addEventListener('click',e=>{const tab=e.target.closest('[data-ads-pane]');if(!tab)return;const active=tab.dataset.adsPane;drawer.querySelectorAll('[data-ads-pane]').forEach(b=>b.setAttribute('aria-pressed',String(b===tab)));document.getElementById('ads-rules-pane').hidden=active!=='rules';document.getElementById('ads-amortization-pane').hidden=active!=='amortization';});
 // Move existing nodes, retaining their render hooks, event handlers and storage.
 const notes=document.createElement('details');notes.id='finance-method-notes';notes.className='mapping';notes.innerHTML='<summary>口径与数据说明</summary>';
 const foot=document.querySelector('#panel-ledger .footer');foot.after(notes);
 for(const id of ['ledger-caption','advertising-columns-note','scope-reconciliation']){const el=document.getElementById(id);if(el)notes.append(el);}
 const expenses=document.createElement('details');expenses.id='finance-expense-overview';expenses.className='mapping';expenses.innerHTML='<summary>业务费用概览</summary>';notes.before(expenses);expenses.append(document.getElementById('expense-summary'),document.getElementById('expense-caption'));
 const originalTotals=document.createElement('details');originalTotals.id='finance-original-totals';originalTotals.className='mapping';originalTotals.innerHTML='<summary>原口径收支核对（非双口径利润）</summary>';expenses.before(originalTotals);originalTotals.append(document.getElementById('totals'));
 document.getElementById('missing').open=false;
 const opened=new Map();
 rules.addEventListener('toggle',e=>{if(e.target.id)opened.set(e.target.id,e.target.open);},true);
 function fold(id,title,nodes){let el=document.getElementById(id);if(el)return el;el=document.createElement('details');el.id=id;el.className='ads-disclosure';el.innerHTML='<summary>'+esc(title)+'</summary>';el.open=opened.get(id)||false;nodes[0].before(el);el.append(...nodes);return el;}
 function tidyRules(){const body=document.getElementById('recharge-body');if(!body)return;
  const taxTreatment=document.getElementById('recharge-tax-treatment');if(taxTreatment){taxTreatment.value='expense';taxTreatment.closest('label').hidden=true;}
  for(const id of ['recharge-channel','recharge-manual-channel']){const select=document.getElementById(id),option=select?.querySelector('option[value="outside"]');if(option)option.disabled=/^SPKJ/.test(document.getElementById('recharge-shop').value);}
  const toolbar=body.querySelector('.toolbar');if(toolbar&&!toolbar.classList.contains('ads-toolbar')){toolbar.classList.add('ads-toolbar');const exportButton=document.getElementById('recharge-export'),fileLabel=document.getElementById('recharge-import').closest('label');const backup=document.createElement('details');backup.className='ads-disclosure';backup.innerHTML='<summary>备份与导入</summary><div class="ads-backup"></div>';body.append(backup);backup.lastElementChild.append(exportButton,fileLabel);}
  const form=document.getElementById('recharge-channel')?.closest('div');if(form){form.hidden=true;form.style.setProperty('display','none','important');const heading=body.querySelector('h3');if(heading){heading.hidden=true;if(heading.nextElementSibling?.classList.contains('caption'))heading.nextElementSibling.hidden=true;}}
  if(toolbar){toolbar.hidden=true;toolbar.style.setProperty('display','none','important');}
  const first=body.querySelector('.table-wrap');if(first&&!first.closest('#ads-rule-history')){first.classList.add('ads-rules-table');const historical=Array.from(first.querySelectorAll('tbody tr')).filter(tr=>tr.textContent.includes('已修改替换，仅保留历史'));
   if(historical.length&&!document.getElementById('ads-rule-history')){const clone=first.cloneNode(true);clone.querySelector('tbody').replaceChildren(...historical);const history=document.createElement('details');history.id='ads-rule-history';history.className='ads-disclosure';history.innerHTML='<summary>历史版本（'+historical.length+'）</summary>';history.open=opened.get(history.id)||false;history.append(clone);first.after(history);}
  }
  const heading=Array.from(body.querySelectorAll('h3')).find(h=>h.textContent==='扣款候选与确认');if(heading&&!document.getElementById('ads-confirmation-section')){const nodes=[];let node=heading;while(node){if(node!==heading&&node.matches('p.notice.warn'))break;nodes.push(node);node=node.nextElementSibling;}const section=fold('ads-confirmation-section','扣款候选与确认',nodes);heading.hidden=true;section.querySelector('.table-wrap')?.classList.add('ads-candidates-table');}
 }
 const observer=new MutationObserver(tidyRules);observer.observe(document.getElementById('recharge-body'),{childList:true});tidyRules();
 function syncLazadaChannel(){const select=document.getElementById('ads-days-channel'),shop=document.getElementById('ads-days-shop')?.value||'',option=select?.querySelector('option[value="outside"]'),insideOnly=/^(LZ|SPKJ)/.test(shop);if(option){option.hidden=option.disabled=insideOnly;if(insideOnly)select.value='inside';}}
 amortization.addEventListener('change',syncLazadaChannel);
 function syncLayout(){
  const scope=[state.filters.platform,state.filters.store,state.filters.month].join('|');
  if(scope!==lastScope){lastScope=scope;const selected=allShops.find(s=>String(s.id)===state.filters.store)||allShops.find(s=>state.filters.platform==='lazada'?s.code.startsWith('LZ'):s.code==='SP6TH')||allShops[0];document.getElementById('ads-rule-shop').value=selected.code;document.getElementById('ads-rule-month').value=state.filters.month||'2026-09';resetRule();}
  button.hidden=!!state.filters.platform&&!['shopee','lazada'].includes(state.filters.platform);if(drawer.open&&button.hidden)drawer.close();
  drawer.querySelector('.drawer-head .caption').textContent='SP／LZ共用 · 规则按店铺保存 · LZ仅站内广告 · 仅当前浏览器生效';
  syncRuleForm();tidyRules();syncLazadaChannel();
 }
 const previous=renderLedger;renderLedger=function(){previous();syncLayout();};syncLayout();
 document.getElementById('ledger-table').addEventListener('click',e=>{const trigger=e.target.closest('[data-ads-detail]');if(!trigger)return;const detail=HTML2_ADVERTISING_COLUMNS.cellDetails[Number(trigger.dataset.adsDetail)];if(!detail)return;
  if(detail.kind==='reclassification'){openDrawer('店铺调整 · 广告充值重分类','<p class="caption">已识别并转入广告口径的充值不再留在主表店铺调整里。原始扣款仍保留在流水明细；利润继续从原始收支加回一次，不因本次展示调整再加回一次。</p><table class="composition"><thead><tr><th>调整构成</th><th>'+esc(detail.currency)+'</th></tr></thead><tbody><tr><td>原店铺调整</td><td>'+moneyDetail(detail.original)+'</td></tr><tr><td>移出已匹配广告充值</td><td>'+format(detail.addback)+'</td></tr><tr class="balance"><td>主表剩余店铺调整</td><td>'+moneyDetail(detail.net)+'</td></tr></tbody></table><details class="mapping"><summary>查看已识别充值来源（'+detail.records.length+'笔）</summary><div class="table-wrap"><table><thead><tr><th>日期</th><th>来源ID</th><th>含税扣款</th></tr></thead><tbody>'+detail.records.map(r=>'<tr><td>'+esc(r.date)+'</td><td>'+esc(r.id)+'</td><td>-'+esc(r.debit)+'</td></tr>').join('')+'</tbody></table></div></details>');return;}
  const operation=detail.key==='operations',title=(operation?'运营':'财务')+'口径 · 广告费用构成';
  const content=detail.reports.map(r=>{const late=r.lateAdvertising?.[detail.key]||0n,edit=-(r.ledgerManual?.[detail.key]||0n)/10000n,parts=operation?[['广告实际消耗（站内及已获取站外）',r.spend],['已核实税额（已含相同税项不重复）',r.operations-r.spend-late-edit]]:[['站内充值周期分摊',r.inside],['站外充值周期分摊',r.outside]];
   const visibleParts=r.lazada?(operation?[['站内Sponsored Max实际消耗',r.spend],['人工税率计算的充值税额分摊（已含税不重复）',r.operations-r.spend-late-edit]]:[['站内充值扣款按实际周期日摊',r.finance-late-edit]]):r.crossBorder?(operation?[['广告实际消耗',r.spend],['已核实充值税额（已含税不重复）',r.operations-r.spend-late-edit]]:[['拨款周期广告充值扣款',r.finance-late-edit]]):parts;
   if(edit!==0n)visibleParts.push(['流水明细费用变动（本地）',edit]);
   if(late!==0n)visibleParts.push(['已关账期间后补／更正调整',late]);
   const actualDaily=operation&&r.actualSource?'<p class="caption">Shopee官方广告日报 · '+esc(r.actualSource.endpoint)+' · '+esc(r.actualSource.timezone)+' · 获取时间 '+esc(r.actualSource.fetchedAt)+'</p><details><summary>广告实际消耗日报（'+r.actualDetails.length+'天）</summary><table><thead><tr><th>消耗日期</th><th>'+esc(r.currency)+'</th></tr></thead><tbody>'+r.actualDetails.map(f=>'<tr><td>'+esc(f.date)+'</td><td>'+esc(f.amount)+'</td></tr>').join('')+'</tbody></table></details>':'';
   const account=r.lazada?'<details><summary>账户流水原额（'+r.accountRows.length+'条；广告充值为其子集，不重复计费）</summary><table><thead><tr><th>日期／来源ID</th><th>类型</th><th>原额 '+esc(r.currency)+'</th><th>快照</th></tr></thead><tbody>'+r.accountRows.map(t=>'<tr><td>'+esc(t.time)+'<small>'+esc(t.id)+'</small></td><td>'+esc(t.type)+' / '+esc(t.sub_type)+'</td><td>'+esc(t.amount)+'</td><td>#'+esc(t.snapshotId)+'</td></tr>').join('')+'</tbody></table></details>':'';
   const scope=r.lazada?'<details><summary>全部科目核算范围核对</summary><p class="caption">财务按各笔交易日期；成本、回冲和仓库保留各自依据日期。订单范围不同的部分列示待核，不按销售额补摊。仓库其他费沿用完整国家账单固定分母，筛选不重算；商品退款不自动回冲成本。</p><table><thead><tr><th>科目</th><th>记录数</th><th>关联订单</th><th>不在本月销售订单中</th><th>待核／缺汇率记录</th></tr></thead><tbody>'+r.scopeDetails.map(t=>'<tr><td>'+esc(t.label)+'</td><td>'+t.rows+'</td><td>'+t.orders+'</td><td>'+t.outside+'</td><td>'+t.pending+'</td></tr>').join('')+'</tbody></table></details>':'';
   return'<h3>'+esc(r.shop)+' · '+esc(r.month)+'</h3>'+actualDaily+account+scope+'<table class="composition"><thead><tr><th>费用构成</th><th>'+esc(r.currency)+'</th></tr></thead><tbody>'+visibleParts.map(([label,amount])=>'<tr><td>'+label+'</td><td>'+moneyDetail(-amount*10000n)+'</td></tr>').join('')+'<tr class="balance"><td>已知部分合计</td><td>'+moneyDetail(-r[detail.key]*10000n)+'</td></tr></tbody></table><p class="notice warn">'+esc(r.warnings.join('；'))+'</p><details class="mapping"><summary>查看充值来源及分摊依据（'+r.details.length+'笔）</summary><div class="table-wrap"><table><thead><tr><th>充值日期／来源ID</th><th>账户</th><th>周期依据</th><th>本月充值归集／摊销</th><th>本月税额摊销（适用时）</th></tr></thead><tbody>'+r.details.map(p=>'<tr><td>'+esc(p.date)+'<small class="sub">'+esc(p.id)+(p.payoutId?' · 拨款批次 '+esc(p.payoutId):'')+'</small></td><td>'+(p.channel==='inside'?'站内':'站外共用')+'</td><td>'+esc(p.pending||(p.days==null?p.method:p.days.toFixed(4)+'天 · '+p.method))+'</td><td>'+esc(p.monthGross??'待估算')+'</td><td>'+esc(p.monthTax??(r.crossBorder||r.lazada?'未核实，不重复叠加':'待估算'))+'</td></tr>').join('')+'</tbody></table></div></details>';}).join('');
  const calculation=detail.kind==='profit'?'<h3>利润试算过程 · '+esc(detail.currency)+'</h3><table class="composition"><tbody><tr><td>原口径收支差额</td><td>'+moneyDetail(detail.basis)+'</td></tr><tr><td>移出原已计入的广告费用</td><td>'+moneyDetail(-detail.oldAds)+'</td></tr><tr><td>加回店铺调整中已转入广告口径的同笔充值</td><td>'+format(detail.addback)+'</td></tr><tr><td>扣除本口径广告费用</td><td>'+moneyDetail(-detail.amount*10000n)+'</td></tr><tr class="balance"><td>利润已知部分（缺项待核）</td><td>'+moneyDetail(detail.profit)+'</td></tr></tbody></table><p class="caption">跨境店拨款周期充值从店铺调整移出，再按本口径扣除，避免重复。其他缺少分摊依据的扣款保留待核。</p>':'';
  openDrawer(detail.kind==='profit'?(operation?'运营':'财务')+'口径 · 利润试算':title,'<p class="caption">两种口径不相加。SP跨境店：运营看实际消耗，财务看拨款周期充值。Lazada及SP本土店：完整充值周期按实际天数分摊，未结束周期才预估。缺成本、日期或费用依据时仅为已知部分。</p>'+(detail.wrongCurrency?'<p class="notice warn">当前展示币种与原币不同，缺少折算依据；下方保留原币构成，不计为已折算金额。</p>':'')+calculation+content+(detail.other?'<p>其他平台原口径广告费用：-'+format(detail.other)+' '+esc(detail.currency)+'</p>':''));
 });
 function moneyDetail(n){return(Number(n)/1000000).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});}
})();
