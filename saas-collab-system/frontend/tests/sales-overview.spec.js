import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import { aggregateTrend, chartGeometry, completedDateRange } from '../src/views/sales-management/overviewTrend';
import SalesOverviewPanel from '../src/views/sales-management/SalesOverviewPanel.vue';

const rows = [
  { date: '2026-09-06', gross_sales: { PHP: '100', THB: '500' }, net_sales: { PHP: '-20' }, refund_amount: { PHP: '120' } },
  { date: '2026-09-07', gross_sales: { PHP: '0' }, net_sales: { PHP: '0' } },
  { date: '2026-09-08', gross_sales: { PHP: '40' }, refund_amount: { PHP: '2' } }
];
describe('销售总览趋势数据', () => {
  it('uses completed calendar days for quick ranges across months and leap years', () => {
    expect(completedDateRange(7, new Date(2026, 8, 11))).toEqual(['2026-09-04', '2026-09-10']);
    expect(completedDateRange(1, new Date(2024, 2, 1))).toEqual(['2024-02-29', '2024-02-29']);
    expect(completedDateRange(30, new Date(2026, 0, 2))).toEqual(['2025-12-03', '2026-01-01']);
  });
  it('keeps zero, negative and missing values distinct and isolates currency', () => {
    const points = aggregateTrend(rows, 'PHP');
    expect(points.map(row => row.gross_sales)).toEqual([100, 0, 40]);
    expect(points.map(row => row.net_sales)).toEqual([-20, 0, null]);
    expect(aggregateTrend(rows, 'THB').map(row => row.gross_sales)).toEqual([500, null, null]);
  });
  it('retains the complete selected interval, sorts dates and excludes invalid dates', () => {
    const data = Array.from({ length: 31 }, (_, i) => ({ date: `2026-08-${String(i + 1).padStart(2, '0')}`, net_sales: { PHP: '1' } }));
    const points = aggregateTrend([...data.reverse(), { date: '2026-02-30' }, { date: 'invalid' }], 'PHP');
    expect(points).toHaveLength(31);
    expect(points[0].date).toBe('2026-08-01');
  });
  it('draws gaps for missing values, includes negative values and handles zero-only plots', () => {
    const points = [{ date: '1', net_sales: -1 }, { date: '2', net_sales: null }, { date: '3', net_sales: 0 }];
    const chart = chartGeometry(points, ['net_sales']);
    expect(chart.paths[0].path.match(/M/g)).toHaveLength(2);
    expect(chart.paths[0].path).not.toMatch(/NaN|Infinity/);
    expect(chart.ticks[0].value).toBeLessThan(-1);
    expect(chartGeometry([{ net_sales: 0 }], ['net_sales']).hasValues).toBe(true);
    expect(chartGeometry(points, []).hasValues).toBe(false);
  });
});

describe('销售总览交互', () => {
  const render = () => mount(SalesOverviewPanel, { props: { currencyCode: 'PHP', data: {
    trend: rows,
    currency_groups: [
      { currency: 'PHP', metrics: [{ code: 'gross_sales', value: '140', unit: 'PHP', label: 'Sales' }] },
      { currency: 'THB', metrics: [{ code: 'gross_sales', value: '500', unit: 'THB', label: 'Sales' }] }
    ]
  } }, global: { stubs: { 'el-empty': { props: ['description'], template: '<p>{{ description }}</p>' }, 'el-table': true, 'el-table-column': true } } });
  it('follows the supplied currency without duplicate currency or period controls', async () => {
    const wrapper = render();
    expect(wrapper.find('.performance-strip').text()).toContain('140.00');
    expect(wrapper.find('select').exists()).toBe(false);
    expect(wrapper.find('.period-switch').exists()).toBe(false);
    await wrapper.setProps({ currencyCode: 'THB' });
    expect(wrapper.find('.performance-strip').text()).toContain('500.00');
    expect(wrapper.find('svg').attributes('aria-label')).toContain('THB');
    await wrapper.setProps({ data: {} });
    expect(wrapper.find('.performance-strip').exists()).toBe(false);
    expect(wrapper.find('svg').exists()).toBe(false);
  });
  it('removes overview tabs but retains the summary header and chart toggle', async () => {
    const wrapper = render();
    await wrapper.find('[role=tab]').trigger('keydown', { key: 'ArrowRight' });
    await wrapper.setProps({ reportKind: 'overview' });
    expect(wrapper.find('[role=tablist]').exists()).toBe(false);
    expect(wrapper.find('.interval-table').exists()).toBe(false);
    expect(wrapper.find('.analysis-toolbar h2').text()).toBe('汇总数据（PHP）');
    expect(wrapper.find('.performance-heading h3').exists()).toBe(false);
    expect(wrapper.find('svg').attributes('aria-label')).toContain('订单汇总明细');
    await wrapper.find('.chart-toggle input').setValue(false);
    expect(wrapper.find('svg').exists()).toBe(false);
    expect(wrapper.find('.performance-strip').exists()).toBe(true);
  });
  it('removes only store report tabs and resets an existing interval view', async () => {
    const wrapper = render();
    await wrapper.find('[role=tab]').trigger('keydown', { key: 'ArrowRight' });
    await wrapper.setProps({ storeReport: true, reportKind: 'stores' });
    expect(wrapper.find('[role=tablist]').exists()).toBe(false);
    expect(wrapper.find('.interval-table').exists()).toBe(false);
    expect(wrapper.find('.analysis-toolbar h2').text()).toBe('店铺概览');
    expect(wrapper.find('.performance-strip').exists()).toBe(true);
    expect(wrapper.find('svg').exists()).toBe(true);
    expect(wrapper.find('[role=region]').attributes('aria-labelledby')).toBe('overview-panel-PHP-heading');
    await wrapper.setProps({ storeReport: false, reportKind: 'skus' });
    expect(wrapper.findAll('[role=tab]')).toHaveLength(2);
  });
  it('uses SKU cards to toggle monetary and count curves on separate axes', async () => {
    const wrapper = render();
    await wrapper.setProps({ reportKind: 'skus', data: { currency_groups: [{currency:'PHP',metrics:[
      {code:'gross_sales',label:'商品金额',value:'1000',unit:'PHP'},
      {code:'units_sold',label:'商品销量',value:'2',unit:'件'}
    ]}], trend:[{date:'2026-09-01',gross_sales:{PHP:'1000'},units_sold:{PHP:'2'}}] } });
    expect(wrapper.find('.chart-legend').exists()).toBe(false);
    const buttons = wrapper.findAll('.metric-toggle');
    expect(buttons[0].attributes('aria-pressed')).toBe('true');
    expect(buttons[1].attributes('aria-pressed')).toBe('false');
    await buttons[1].trigger('click');
    expect(wrapper.vm.geometry.paths).toHaveLength(2);
    expect(wrapper.vm.countGeometry.hasValues).toBe(true);
    await wrapper.find('.chart-hit').trigger('focus');
    expect(wrapper.find('.chart-tooltip').text()).toContain('商品销量：2 件');
    await buttons[0].trigger('click'); await buttons[1].trigger('click');
    expect(wrapper.find('svg').exists()).toBe(false);
    expect(wrapper.text()).toContain('请选择至少一个趋势指标');
  });
  it('toggles overview cards using full daily order fields and isolates business ratios', async () => {
    const wrapper = render();
    await wrapper.setProps({ reportKind:'overview', data:{order_currency_groups:[{currency:'PHP',metrics:[{code:'order_count',label:'订单总量',value:'10',unit:'单'}]}],order_daily:[{date:'2026-09-01',currency:'PHP',order_count:10},{date:'2026-09-01',currency:'THB',order_count:999}]} });
    expect(wrapper.find('.chart-legend').exists()).toBe(false);
    await wrapper.find('.metric-toggle').trigger('click');
    expect(wrapper.vm.countGeometry.paths[0].points[0].value).toBe(10);
    await wrapper.setProps({reportKind:'business',chartMetrics:[{code:'gross_sales',label:'销售额',unit:'PHP'},{code:'cancellation_rate',label:'取消率',unit:''}],data:{metric_daily:[{date:'2026-09-01',currency:'PHP',gross_sales:'1000',cancellation_rate:'0.25'}]} });
    wrapper.vm.toggleSeries('cancellation_rate');
    expect(wrapper.vm.selected).toEqual(['cancellation_rate']);
    expect(wrapper.vm.geometry.paths[0].points[0].value).toBe(25);
    expect(wrapper.vm.seriesValue('0.25','cancellation_rate')).toBe('25.00%');
    wrapper.vm.toggleSeries('gross_sales');
    expect(wrapper.vm.selected).toEqual(['gross_sales']);
  });
  it('uses store cards to toggle daily counts while keeping tabs and legend removed', async () => {
    const wrapper = render();
    await wrapper.setProps({ storeReport:true, reportKind:'stores', data:{currency_groups:[{currency:'PHP',metrics:[{code:'units_sold',label:'产品销量',value:'12',unit:'units'}]}],metric_daily:[{date:'2026-09-01',currency:'PHP',units_sold:12}]} });
    expect(wrapper.find('.chart-legend').exists()).toBe(false);
    expect(wrapper.find('[role=tablist]').exists()).toBe(false);
    const card = wrapper.find('.metric-toggle');
    await card.trigger('click');
    expect(card.attributes('aria-pressed')).toBe('true');
    expect(wrapper.vm.countGeometry.paths[0].points[0].value).toBe(12);
    await card.trigger('click');
    expect(wrapper.find('svg').exists()).toBe(false);
    expect(wrapper.find('.performance-strip').exists()).toBe(true);
  });
  it('labels every date, reserves readable spacing and uses integer quantity ticks', async () => {
    const wrapper = render();
    const trend = Array.from({length:31}, (_, i) => ({date:`2026-08-${String(i+1).padStart(2,'0')}`,gross_sales:{PHP:'10000'}}));
    await wrapper.setProps({data:{currency:'PHP',trend}});
    expect(wrapper.findAll('.chart-dates text')).toHaveLength(31);
    expect(wrapper.findAll('.chart-dates text')[30].text()).toBe('2026-08-31');
    expect(wrapper.vm.dateTicks[1].x - wrapper.vm.dateTicks[0].x).toBe(110);
    expect(wrapper.vm.axisNumber(123456)).toBe('12.35万');
    expect(wrapper.vm.axisNumber(100000000)).toBe('1亿');
    expect(chartGeometry([{units:2}], ['units'], {integer:true}).ticks.every(tick => Number.isInteger(tick.value))).toBe(true);
  });
  it('keeps daily points and supports legend toggles and keyboard tab changes', async () => {
    const wrapper = render();
    expect(wrapper.find('svg').attributes('aria-label')).toContain('3 个日期');
    for (const button of wrapper.findAll('.chart-legend button')) await button.trigger('click');
    expect(wrapper.text()).toContain('请选择至少一个趋势指标');
    await wrapper.find('[role=tab]').trigger('keydown', { key: 'ArrowRight' });
    expect(wrapper.findAll('[role=tab]')[1].attributes('aria-selected')).toBe('true');
    expect(wrapper.find('.interval-table').exists()).toBe(true);
    expect(wrapper.find('.chart-toggle').exists()).toBe(false);
  });
  it('shows all selected values on focus and can hide the chart without hiding metrics', async () => {
    const wrapper = render();
    await wrapper.find('.chart-hit').trigger('focus');
    expect(wrapper.find('.chart-tooltip').text()).toContain('-20.00');
    expect(wrapper.find('.chart-tooltip').text()).toContain('120.00');
    await wrapper.find('.chart-toggle input').setValue(false);
    expect(wrapper.find('svg').exists()).toBe(false);
    expect(wrapper.find('.performance-strip').exists()).toBe(true);
    expect(wrapper.text()).toContain('图表已收起');
    await wrapper.find('.chart-toggle input').setValue(true);
    expect(wrapper.find('svg').exists()).toBe(true);
    expect(wrapper.find('.chart-tooltip').exists()).toBe(false);
  });
});
