import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
const request = vi.hoisted(() => vi.fn());
const confirm = vi.hoisted(() => vi.fn());
const prompt = vi.hoisted(() => vi.fn());
vi.mock('../src/api/request', () => ({ requestApi: request }));
vi.mock('element-plus', async original => ({ ...await original(), ElMessageBox: { confirm, prompt } }));
import WarehouseBillFormat from '../src/components/WarehouseBillFormat.vue';

let wrapper;
const sample = { name: '结算单', sample: [
  { row: 1, cells: { A: '标题' } }, { row: 7, cells: { A: '项目', B: '金额' } },
] };
beforeEach(() => {
  request.mockReset();
  confirm.mockReset(); prompt.mockReset();
  request.mockImplementation(async c => ({ success: true, data: c.url.endsWith('format-rules/')
    ? { results: [] } : c.method === 'post' ? { items: [
      { row: 8, item: '出库', amount: '4' }, { row: 9, item: '入库', amount: '6' },
      { row: 10, item: '合计', amount: '10' },
    ] } : { sheets: [sample] } }));
});
afterEach(() => wrapper?.unmount());
async function setup(disabled = false, initializeNew = true, job = {}) {
  wrapper = mount(WarehouseBillFormat, { props: {
    disabled, job: { id: 'sample-job', summary: { country: 'PH', bill_month: '2026-10', settlement_warehouse_id: 1 }, ...job },
    options: { countries: [{ code: 'PH', name: '菲律宾' }], warehouses: [{ id: 1, code: 'WH', name: '测试仓', country: 'PH' }] },
  }, global: { plugins: [ElementPlus] } });
  await flushPromises();
  if (initializeNew && wrapper.vm.loaded) await wrapper.vm.selectMode('new');
}
describe('warehouse original file format configuration', () => {
  it('loads sheets after its parent finishes polling instead of leaving an empty editor', async () => {
    await setup(true);
    expect(request).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('正在读取原文件工作表');
    await wrapper.setProps({disabled:false}); await flushPromises();
    expect(wrapper.vm.loaded).toBe(true);
    expect(wrapper.vm.specs).toEqual([]);
    await wrapper.vm.selectMode('new');
    expect(wrapper.vm.specs.map(s => s.name)).toEqual(['结算单']);
    expect(wrapper.get('nav').text()).toContain('结算单');
    expect(wrapper.get('nav').text()).toContain('待配置');
    expect(wrapper.text()).toContain('工作表配置 0 / 1');
    expect(wrapper.findAll('button').find(b => b.text() === '解析预览（不登记）').element.disabled).toBe(true);
  });
  it('blocks empty or incomplete rules and allows retry after a sample read failure', async () => {
    request.mockResolvedValue({success:true,data:{sheets:[]}});
    await setup();
    expect(wrapper.vm.loaded).toBe(false);
    expect(wrapper.text()).toContain('未读取到工作表');
    request.mockClear(); await wrapper.vm.saveRule(); wrapper.vm.preview();
    expect(request).not.toHaveBeenCalled(); expect(wrapper.emitted('preview')).toBeUndefined();
    request.mockImplementation(async c => ({success:true,data:c.url.endsWith('format-rules/') ? {results:[]} : {sheets:[sample]}}));
    await wrapper.findAll('button').find(b => b.text() === '重新读取工作表').trigger('click'); await flushPromises();
    expect(wrapper.vm.loaded).toBe(true);
    await wrapper.vm.selectMode('new');
    request.mockClear(); await wrapper.vm.saveRule(); wrapper.vm.preview();
    expect(request).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('请完成每个工作表');
  });
  it('protects unsaved configuration and blocks leaving during processing', async () => {
    await setup(); expect(await wrapper.vm.canLeave()).toBe(true);
    wrapper.vm.spec.kind = 'order';
    confirm.mockRejectedValue('cancel');
    expect(await wrapper.vm.canLeave()).toBe(false);
    confirm.mockResolvedValue('confirm');
    expect(await wrapper.vm.canLeave()).toBe(true);
    wrapper.vm.busy = true; expect(await wrapper.vm.canLeave()).toBe(false);
  });
  it('keeps the entered header and exact columns when loading settlement items', async () => {
    await setup(); wrapper.vm.spec.kind = 'settlement'; await flushPromises();
    const input = wrapper.findAll('input[role="spinbutton"]')[0];
    await input.setValue('7'); await input.trigger('change'); await input.trigger('blur');
    expect(wrapper.vm.spec.header).toBe(7);
    expect(wrapper.vm.columns.map(c => c.column)).toEqual(['A', 'B']);
    wrapper.vm.spec.columns = { item: 'A', amount: 'B' };
    await wrapper.vm.loadItems();
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ method: 'post',
      data: { spec: expect.objectContaining({ header: 7, columns: { item: 'A', amount: 'B' } }) } }));
    expect(input.element.value).toBe('7');
    expect(wrapper.vm.sheetState(wrapper.vm.spec)).toBe('待核对');
    wrapper.vm.spec.items = { 出库: { role: 'order' }, 入库: { role: 'other' }, 合计: { role: 'total' } };
    expect(wrapper.vm.sheetState(wrapper.vm.spec)).toBe('已配置');
    wrapper.vm.spec.items.入库 = { role: 'ignore', reason: '' };
    expect(wrapper.vm.sheetState(wrapper.vm.spec)).toBe('待核对');
  });
  it('saves server rules with current-file month only in preview and never registers fees', async () => {
    await setup();
    wrapper.vm.spec.kind = 'order'; wrapper.vm.spec.header = 7;
    wrapper.vm.spec.columns = { number: 'A', amount: 'B' };
    wrapper.vm.ruleName = '新格式';
    request.mockClear(); await wrapper.vm.saveRule();
    const writes = request.mock.calls.filter(([c]) => c.method === 'post');
    expect(writes).toHaveLength(1);
    expect(writes[0][0].url).toBe('/api/finance/warehouse-fees/format-rules/');
    expect(writes[0][0].data).toMatchObject({ name: '新格式', warehouse_id: 1,
      config: { schema_version: 3, sheets: [expect.objectContaining({ header: 7, expected: { A: '项目', B: '金额' } })] } });
    expect(writes[0][0].data).not.toHaveProperty('bill_month');
    wrapper.vm.preview();
    expect(wrapper.emitted('preview')[0][0]).toMatchObject({ bill_month: '2026-10', warehouse_id: 1 });
  });
});


it('updates a selected rule with its version, and copies without overwriting its identity', async () => {
  await setup();
  const rule = {id:7, version:2, name:'原格式', country:'PH', warehouse_id:1, config:{schema_version:3,
    sheets:[{name:'结算单',kind:'order',header:7,start:8,columns:{number:'A',amount:'B'},group_by:'A',filters:[{column:'B',values:['4']}],skip_zero:true}]}};
  wrapper.vm.rules = [rule]; wrapper.vm.ruleMode = 'edit'; wrapper.vm.ruleId = 7; wrapper.vm.useRule(7);
  expect(wrapper.vm.ruleName).toBe('原格式');
  request.mockImplementation(async c => ({success:true,data:c.method === 'post' ? {...rule,version:3} : {results:[{...rule,version:3}]}}));
  await wrapper.vm.saveRule();
  expect(request).toHaveBeenCalledWith(expect.objectContaining({method:'post',data:expect.objectContaining({id:7,version:2,name:'原格式'})}));
  prompt.mockResolvedValue({value:'原格式（副本）'});
  request.mockClear(); await wrapper.vm.saveAs();
  const payload = request.mock.calls.find(([c]) => c.method === 'post')[0].data;
  expect(payload.name).toBe('原格式（副本）'); expect(payload).not.toHaveProperty('id');
  expect(payload.config.sheets[0]).toMatchObject({start:8,group_by:'A',filters:[{column:'B',values:['4']}],skip_zero:true});
  expect(rule.config.sheets[0].columns).toEqual({number:'A',amount:'B'});
});

it('allows a separate total cell without requiring a total row in the category table', async () => {
  await setup();
  const spec = {kind:'settlement',columns:{item:'A',amount:'B'},items:{处理费:{role:'order'},仓租:{role:'other'}},total_source:'E3'};
  expect(wrapper.vm.sheetState(spec)).toBe('已配置');
  spec.items.合计={role:'total'};
  expect(wrapper.vm.sheetState(spec)).toBe('待核对');
});

it('preserves warehouse validation on ignored supporting sheets when a rule is edited', async () => {
  await setup();
  wrapper.vm.specs=[{name:'结算单',kind:'ignore',reason:'辅助仓库清单',warehouse_column:'A',warehouse_header:1,warehouse_values:['SA_01']}];
  const config=wrapper.vm.configuration();
  expect(config.sheets[0]).toMatchObject({warehouse_column:'A',warehouse_header:1,warehouse_values:['SA_01']});
});

it('attributes an unchanged saved-rule preview but not unsaved changes to that rule', async () => {
  await setup();
  wrapper.vm.rules=[{id:7,country:'PH',warehouse_id:1,name:'有成功记录的规则',successful_files:['九月账单.xlsx'],
    config:{schema_version:3,sheets:[{name:'结算单',kind:'order',header:7,columns:{number:'A',amount:'B'}}]}}];
  wrapper.vm.ruleMode='edit';wrapper.vm.ruleId=7;wrapper.vm.useRule(7);
  wrapper.vm.preview();
  expect(wrapper.emitted('preview')[0][0]).toMatchObject({format_rule_id:7});
  expect(wrapper.emitted('preview')[0][0]).not.toHaveProperty('format_config');
  wrapper.vm.spec.columns={number:'B',amount:'A'};wrapper.vm.preview();
  expect(wrapper.emitted('preview')[1][0]).toHaveProperty('format_config');
  expect(wrapper.emitted('preview')[1][0]).not.toHaveProperty('format_rule_id');
});

it('shows successful filenames on rule hover', async () => {
  await setup();
  wrapper.vm.rules=[{id:7,country:'PH',warehouse_id:1,name:'已解析规则',warehouse_code:'WH',successful_files:['九月账单.xlsx','十月账单.xlsx']}];
  wrapper.vm.ruleMode='edit';await flushPromises();
  const tooltip=wrapper.findAllComponents({name:'ElTooltip'}).find(c=>c.props('showAfter')===250);
  expect(tooltip.exists()).toBe(true);
  await wrapper.get('[aria-label="已保存格式规则"]').trigger('click');await flushPromises();
  const label=document.querySelector('.rule-option-label');expect(label).not.toBeNull();
  label.dispatchEvent(new MouseEvent('mouseenter',{bubbles:true}));await new Promise(resolve=>setTimeout(resolve,350));await flushPromises();
  expect(document.body.textContent).toContain('九月账单.xlsx');
  expect(document.body.textContent).toContain('十月账单.xlsx');
});

it('rejects a different workbook rule without partially applying it or changing ownership', async () => {
  await setup();
  const before=JSON.stringify(wrapper.vm.specs);
  wrapper.vm.rules=[{id:17,country:'MY',warehouse_id:9,name:'错误国家规则',config:{schema_version:3,sheets:[{name:'代发费',kind:'order',header:1,columns:{number:'A',amount:'B'}}]}}];
  wrapper.vm.ruleMode='edit';wrapper.vm.ruleId=17;wrapper.vm.useRule(17);
  expect(wrapper.vm.error).toContain('国家');expect(wrapper.vm.ruleId).toBeNull();
  expect(wrapper.vm.country).toBe('PH');expect(wrapper.vm.warehouseId).toBe(1);
  expect(JSON.stringify(wrapper.vm.specs)).toBe(before);
  wrapper.vm.rules[0].country='PH';wrapper.vm.ruleId=17;wrapper.vm.useRule(17);
  expect(wrapper.vm.error).toContain('另存为');
  expect(wrapper.vm.requiresSaveAs).toBe(true);
});

it('allows explicit copying of a different layout with a warning instead of editing the source rule', async () => {
  await setup();
  wrapper.vm.rules=[{id:17,country:'PH',warehouse_id:1,name:'旧布局',config:{schema_version:3,sheets:[{name:'旧结算单',kind:'order',header:1,columns:{number:'A',amount:'B'}}]}}];
  wrapper.vm.ruleMode='edit';wrapper.vm.ruleId=17;wrapper.vm.useRule(17);
  expect(wrapper.vm.ruleName).toBe('旧布局');
  expect(wrapper.vm.error).toContain('原规则不会被覆盖');
  expect(wrapper.vm.specs[0].name).toBe('旧结算单');expect(wrapper.vm.specs[0].kind).toBe('order');
  expect(wrapper.vm.configurationReady).toBe(false);
  wrapper.vm.mapSheet('旧结算单','结算单');
  expect(wrapper.vm.specs).toHaveLength(1);
  expect(wrapper.vm.specs[0].columns).toEqual({number:'A',amount:'B'});
  wrapper.vm.month='';
  expect(wrapper.vm.configurationReady).toBe(false);
});

const storedRule = {id:31,version:4,name:'保存的格式',country:'PH',warehouse_id:1,config:{schema_version:3,sheets:[
  {name:'结算单',kind:'settlement',header:7,columns:{item:'A',amount:'B'},expected:{A:'项目',B:'金额'},items:{出库:{role:'order'},合计:{role:'total'}}}
]}};

it.each(['new','edit'])('preserves flexible extraction and missing known auxiliaries when saving %s formats', async mode => {
  const config=JSON.parse(JSON.stringify(storedRule.config));
  Object.assign(config.sheets[0],{header_mode:'fields',settlement_auto:'total_row',sheet_aliases:['历史结算单'],field_aliases:{A:['费用项目']},
    total_source:'B10',items:{出库:{role:'order'},仓租:{role:'other'}}});
  config.sheets.push({name:'已知辅助表',kind:'ignore',optional_sheet:true,reason:'不重复计费'});
  const rule={...storedRule,config};
  request.mockImplementation(async c=>({success:true,data:c.url.endsWith('format-rules/')
    ? c.method==='post' ? {...rule,version:5} : {results:[rule]}
    : {sheets:[sample],rule_resolutions:{31:{version:4,config}}}}));
  await setup(false,false,{overrides:{order_warehouse:true}});
  await wrapper.vm.selectRule(31);
  if(mode==='new') {wrapper.vm.ruleMode='new';wrapper.vm.ruleId=null;wrapper.vm.ruleName='新取数格式';}
  expect(wrapper.vm.layoutReady).toBe(true);
  expect(wrapper.text()).toContain('按字段名称自动查找');
  expect(wrapper.text()).toContain('已知备用工作表名称');
  request.mockClear();await wrapper.vm.saveRule();
  const saved=request.mock.calls.find(([c])=>c.method==='post')[0].data;
  expect(saved.config.sheets[0]).toMatchObject({header_mode:'fields',settlement_auto:'total_row',sheet_aliases:['历史结算单']});
  expect(saved.config.sheets[0].field_aliases).toEqual({A:['费用项目']});
  expect(saved.config.sheets[0].items.仓租.role).toBe('other');
  expect(saved.config.sheets[1]).toMatchObject({name:'已知辅助表',optional_sheet:true});
  expect(saved.warehouse_id).toBeNull();
  if(mode==='edit')expect(saved).toMatchObject({id:31,version:4});
  else expect(saved.id).toBeUndefined();
});
function mockRules(rules) {
  request.mockImplementation(async c => ({success:true,data:c.url.endsWith('format-rules/') ? {results:rules} : {sheets:[sample]}}));
}

it('configures extraction steps from blank and persists explicit total strategies', async () => {
  await setup();
  Object.assign(wrapper.vm.spec,{kind:'settlement',header:7,columns:{item:'A',amount:'B'},items:{出库:{role:'order'}}});
  wrapper.vm.ruleName='自定义取数逻辑';
  await flushPromises();
  expect(wrapper.text()).toContain('一、确定这张表的用途');
  expect(wrapper.text()).toContain('二、找到字段名称所在的行');
  expect(wrapper.text()).toContain('四、确定读取哪些明细');
  expect(wrapper.text()).toContain('五、核对账单总额和费用分类');
  wrapper.vm.setTotalMode('sequence_total');
  expect(wrapper.vm.configuration(false).sheets[0].settlement_auto).toBe('sequence_total');
  wrapper.vm.setTotalMode('sum');
  expect(wrapper.vm.configuration(false).sheets[0]).toMatchObject({total_source:'sum'});
  expect(wrapper.vm.spec.settlement_auto).toBeUndefined();
  wrapper.vm.setTotalMode('cell');
  expect(wrapper.vm.totalMode).toBe('cell');
  expect(wrapper.vm.spec.total_source).toBeUndefined();
  expect(wrapper.vm.sheetState(wrapper.vm.spec)).toBe('待核对');
  wrapper.vm.spec.total_source='B10';
  expect(wrapper.vm.configuration(false).sheets[0].total_source).toBe('B10');
  wrapper.vm.setTotalMode('project');
  expect(wrapper.vm.spec.total_source).toBeUndefined();
  wrapper.vm.setTotalMode('total_row');
  expect(wrapper.vm.spec.settlement_auto).toBe('total_row');
  expect(wrapper.vm.ruleId).toBeNull();
});
it('automatically fills a unique matching rule including its saved item roles', async () => {
  mockRules([storedRule]); await setup(false,false);
  expect(wrapper.vm.ruleId).toBe(31); expect(wrapper.vm.ruleMode).toBe('edit');
  expect(wrapper.vm.configuredCount).toBe(1); expect(wrapper.vm.configurationReady).toBe(true);
  expect(wrapper.vm.items.map(i=>i.item)).toEqual(['出库','合计']);
});
it('requires selection for ambiguous rules rather than starting a blank editor', async () => {
  mockRules([storedRule,{...storedRule,id:32}]); await setup(false,false);
  expect(wrapper.vm.specs).toEqual([]); expect(wrapper.vm.ruleId).toBeNull();
  expect(wrapper.text()).toContain('多个匹配规则');
  await wrapper.vm.selectRule(31); expect(wrapper.vm.configuredCount).toBe(1);
});
it('only initializes a new blank format on explicit request', async () => {
  mockRules([{...storedRule,config:{...storedRule.config,sheets:[{...storedRule.config.sheets[0],expected:{A:'不匹配'}}]}}]);
  await setup(false,false); expect(wrapper.vm.specs).toEqual([]);
  await wrapper.vm.selectMode('new'); expect(wrapper.vm.specs[0].kind).toBe('');
});
it('restores historical configuration with its original version', async () => {
  mockRules([{...storedRule,version:5}]);
  await setup(false,false,{summary:{country:'PH',bill_month:'2026-08',settlement_warehouse_id:1,
    applied_rule:{id:31,name:storedRule.name,record_version:4,config:storedRule.config}}});
  expect(wrapper.vm.specs).toEqual(storedRule.config.sheets);
  expect(wrapper.vm.ruleId).toBe(31); expect(wrapper.vm.month).toBe('2026-08');
  wrapper.vm.preview(); expect(wrapper.emitted('preview')[0][0].format_rule_version).toBe(4);
  await wrapper.vm.saveRule();
  expect(request).toHaveBeenCalledWith(expect.objectContaining({method:'post',data:expect.objectContaining({id:31,version:4})}));
});
it('restores per-batch configuration on reopening', async () => {
  await setup(false,false,{overrides:{format_config:storedRule.config}});
  expect(wrapper.vm.specs).toEqual(storedRule.config.sheets);expect(wrapper.vm.configuredCount).toBe(1);
});
it('preserves edits when switching mode or rule is cancelled', async () => {
  mockRules([storedRule]); await setup(false,false);
  wrapper.vm.spec.items.出库.role='other';confirm.mockRejectedValue('cancel');
  await wrapper.vm.selectMode('new');expect(wrapper.vm.ruleMode).toBe('edit');
  await wrapper.vm.selectRule(null);expect(wrapper.vm.ruleId).toBe(31);
  expect(wrapper.vm.spec.items.出库.role).toBe('other');
});

it('shows all format operations and saved rules before a file is selected', async () => {
 mockRules([storedRule]);
 wrapper=mount(WarehouseBillFormat,{props:{options:{countries:[],warehouses:[]}},global:{plugins:[ElementPlus]}});
 await flushPromises();
 expect(wrapper.text()).toContain('新增取数逻辑');expect(wrapper.text()).toContain('修改已保存逻辑');expect(wrapper.text()).not.toContain('复制已有格式');expect(wrapper.text()).toContain('另存为');
 expect(wrapper.vm.rules).toHaveLength(1);
 expect(request.mock.calls.every(([c])=>c.url.endsWith('format-rules/'))).toBe(true);
 await wrapper.vm.selectRule(31);
 expect(wrapper.vm.ruleId).toBe(31);expect(wrapper.vm.ruleName).toBe('保存的格式');
 expect(wrapper.vm.configurationReady).toBe(false);
 expect(wrapper.emitted('selection').at(-1)[0]).toMatchObject({mode:'edit',id:31});
});
it('keeps a preselected edit operation and rule when the uploaded file is loaded', async () => {
 mockRules([storedRule]);
 wrapper=mount(WarehouseBillFormat,{props:{job:{id:'uploaded',summary:{country:'PH',bill_month:'2026-08'}},initialSelection:{mode:'edit',id:31},options:{countries:[],warehouses:[]}},global:{plugins:[ElementPlus]}});
 await flushPromises();
 expect(wrapper.vm.ruleMode).toBe('edit');expect(wrapper.vm.ruleId).toBe(31);
 expect(wrapper.vm.ruleName).toBe('保存的格式');expect(wrapper.vm.configuredCount).toBe(1);
});
it('keeps an explicit new-format choice instead of automatically editing a matching saved rule', async () => {
 mockRules([storedRule]);
 wrapper=mount(WarehouseBillFormat,{props:{job:{id:'uploaded'},initialSelection:{mode:'new',id:null},options:{countries:[],warehouses:[]}},global:{plugins:[ElementPlus]}});
 await flushPromises();
 expect(wrapper.vm.ruleMode).toBe('new');expect(wrapper.vm.ruleId).toBeNull();expect(wrapper.vm.specs[0].kind).toBe('');
});

it('cancelling save-as leaves the current edits and original rule untouched',async()=>{
 mockRules([storedRule]);await setup(false,false);
 wrapper.vm.spec.items.出库.role='other';prompt.mockRejectedValue('cancel');request.mockClear();
 await wrapper.vm.saveAs();
 expect(request).not.toHaveBeenCalled();expect(wrapper.vm.ruleId).toBe(31);
 expect(wrapper.vm.spec.items.出库.role).toBe('other');
});
it('requires save-as for an adapted workbook instead of overwriting the source rule',async()=>{
 await setup();
 wrapper.vm.rules=[{...storedRule,config:{schema_version:3,sheets:[{name:'旧结算单',kind:'order',header:7,columns:{number:'A',amount:'B'}}]}}];
 wrapper.vm.ruleMode='edit';wrapper.vm.useRule(31);wrapper.vm.mapSheet('旧结算单','结算单');
 request.mockClear();await wrapper.vm.saveRule();expect(request).not.toHaveBeenCalled();
 expect(wrapper.vm.error).toContain('另存为');
});

it('uses manual country and month with a cross-country format and no default order warehouse',async()=>{
 mockRules([storedRule]);
 wrapper=mount(WarehouseBillFormat,{props:{job:{id:'new',file_name:'2026年9月菲律宾.xlsx',overrides:{order_warehouse:true,country:'MY',bill_month:'2026-08'}},options:{countries:[],warehouses:[]}},global:{plugins:[ElementPlus]}});
 await flushPromises();
 expect(wrapper.vm.country).toBe('MY');expect(wrapper.vm.month).toBe('2026-08');
 expect(wrapper.vm.ruleId).toBe(31);expect(wrapper.vm.warehouseId).toBeNull();
 expect(wrapper.vm.configurationReady).toBe(true);
 wrapper.vm.preview();expect(wrapper.emitted('preview')[0][0]).toMatchObject({country:'MY',bill_month:'2026-08',order_warehouse:true,format_rule_id:31});
 expect(wrapper.emitted('preview')[0][0]).not.toHaveProperty('warehouse_id');
 await wrapper.vm.saveRule();expect(request).toHaveBeenCalledWith(expect.objectContaining({method:'post',data:expect.objectContaining({warehouse_id:null})}));
});

it('allows configuring a generic format before requesting manual preview context',async()=>{
 mockRules([storedRule]);
 wrapper=mount(WarehouseBillFormat,{props:{job:{id:'new',overrides:{order_warehouse:true}},options:{countries:[],warehouses:[]}},global:{plugins:[ElementPlus]}});
 await flushPromises();
 expect(wrapper.vm.layoutReady).toBe(true);expect(wrapper.vm.saveReady).toBe(true);
 expect(wrapper.vm.previewContextVisible).toBe(false);
 wrapper.vm.preview();await flushPromises();
 expect(wrapper.vm.previewContextVisible).toBe(true);expect(wrapper.emitted('preview')).toBeUndefined();
 wrapper.vm.country='PH';wrapper.vm.month='2026-09';wrapper.vm.preview();
 expect(wrapper.emitted('preview')[0][0]).toMatchObject({country:'PH',bill_month:'2026-09',order_warehouse:true});
});


it('loads a consolidated monthly rule and preserves absent known fees when saving', async () => {
  const original = {name:'2026年8月账单', kind:'settlement', month_name:true, settlement_auto:'items_in_range', header:7, start:8, end:8, total_source:'sum', columns:{item:'A',amount:'B'}, expected:{A:'项目',B:'金额'}, items:{出库:{role:'order'},仓租:{role:'other'}}};
  const rule = {id:45, version:1, name:'通用格式', country:'', warehouse_id:null, config:{schema_version:3,sheets:[original]}};
  const current = {...original, name:'结算单'};
  request.mockImplementation(async c => ({success:true,data:c.url.endsWith('format-rules/')
    ? c.method === 'post' ? {...rule,version:2} : {results:[rule]}
    : c.method === 'post' ? {items:[{row:8,item:'出库',amount:'4'}]}
    : {sheets:[sample],rule_resolutions:{45:{version:1,config:{schema_version:3,sheets:[current]}}}}}));
  await setup(false,false,{overrides:{order_warehouse:true}});
  expect(wrapper.vm.ruleId).toBe(45);
  expect(wrapper.vm.specs).toHaveLength(1);
  expect(wrapper.vm.spec.name).toBe('结算单');
  await wrapper.vm.loadItems();
  expect(wrapper.vm.spec.items.仓租).toEqual({role:'other'});
  await wrapper.vm.saveRule();
  const saved = request.mock.calls.find(([c]) => c.method === 'post' && c.url.endsWith('format-rules/'))[0].data;
  expect(saved.config.sheets[0]).toMatchObject({month_name:true,settlement_auto:'items_in_range',items:{仓租:{role:'other'}}});
  expect(saved.warehouse_id).toBeNull();
});

it('rebuilds header evidence when reading items after changing the header', async () => {
  await setup();
  wrapper.vm.spec.kind = 'settlement'; await flushPromises();
  wrapper.vm.spec.expected = { A:'旧项目', B:'旧金额' };
  wrapper.vm.spec.header = 7;
  wrapper.vm.spec.columns = { item:'A', amount:'B' };
  await wrapper.vm.loadItems();
  expect(request).toHaveBeenCalledWith(expect.objectContaining({ method:'post', data:{ spec:expect.objectContaining({expected:{A:'项目',B:'金额'}}) } }));
});
