import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { feishuRuleConfig } from '../src/utils/feishuRule';
import { feishuReportLocation, initializeFeishuReportConfig, projectFeishuCard, safeFeishuExternalUrl } from '../src/utils/feishuReportPreview';
import FeishuCardElement from '../src/views/integrations/FeishuCardElement.vue';
import FeishuReportPreviewContent from '../src/views/integrations/FeishuReportPreviewContent.vue';

describe('飞书图表报表预览与详情链接', () => {
  it('保存 chart 格式并保留已有 card/file 选择能力', () => {
    expect(feishuRuleConfig('report', { format: 'chart' })).toMatchObject({ format: 'chart', hour: 9 });
    expect(feishuRuleConfig('report', { format: 'card' }).format).toBe('card');
    expect(feishuRuleConfig('report', { format: 'file' }).format).toBe('file');
  });

  it('仅投影 JSON2 图表白名单字段并保留原生 bar 数据结构', () => {
    const projected = projectFeishuCard({ schema: '2.0', body: { elements: [
      { tag: 'markdown', content: '<script>text only</script>' },
      { tag: 'chart', chart_spec: { type: 'bar', title: { text: '销售额' }, data: { values: [{ country: 'US', value: 12 }, { country: 'CA', value: 'bad' }] }, xField: 'ignored', yField: 'ignored' } },
      { tag: 'button', text: { tag: 'plain_text', content: '登录查看详细报表' }, behaviors: [{ type: 'open_url', default_url: 'https://system.example.com/reports/basic?tab=analysis' }] },
      { tag: 'hr' }, { tag: 'unsupported' }
    ] } });
    expect(projected.elements).toEqual([
      { tag: 'markdown', content: '<script>text only</script>' },
      { tag: 'chart', chart_spec: { type: 'bar', data: { values: [{ country: 'US', value: 12 }] }, xField: 'country', yField: 'value', title: { text: '销售额' } } },
      { tag: 'button', text: '登录查看详细报表', url: 'https://system.example.com/reports/basic?tab=analysis' },
      { tag: 'hr' }
    ]);
    const unsafeButton = projectFeishuCard({ schema: '2.0', body: { elements: [
      { tag: 'button', text: { tag: 'plain_text', content: '不安全链接' }, behaviors: [{ type: 'open_url', default_url: 'javascript:alert(1)' }] }
    ] } });
    expect(unsafeButton.elements[0].url).toBe('');
    expect(safeFeishuExternalUrl('https://example.com/report')).toBe('https://example.com/report');
    expect(safeFeishuExternalUrl('http://example.com')).toBe('');
    expect(safeFeishuExternalUrl('https://user:pass@example.com/report')).toBe('');
  });

  it('实际组件显示后端详情按钮，0和负值按轴方向渲染', () => {
    const button = mount(FeishuCardElement, { props: { element: { tag: 'button', text: '登录查看详细报表', url: 'https://system.example.com/reports/basic' } } });
    expect(button.text()).toContain('登录查看详细报表');
    expect(button.get('a').attributes('href')).toBe('https://system.example.com/reports/basic');

    const chart = mount(FeishuCardElement, { props: { element: { tag: 'chart', chart_spec: {
      type: 'bar', title: { text: '净流水' }, data: { values: [{ country: 'US', value: 0 }, { country: 'CA', value: -8 }] },
      xField: 'country', yField: 'value'
    } } } });
    const bars = chart.findAll('.chart-bar-track i');
    expect(bars[0].attributes('style')).toContain('width: 0%');
    expect(bars[0].classes()).not.toContain('chart-bar--positive');
    expect(bars[1].attributes('style')).toContain('width: 50%');
    expect(bars[1].classes()).toContain('chart-bar--negative');
    expect(chart.text()).toContain('净流水');
    button.unmount(); chart.unmount();
  });

  it('存在 JSON2 卡片时展示卡片元素，不重复堆叠旧摘要和 sections', () => {
    const card = projectFeishuCard({ schema: '2.0', body: { elements: [{ tag: 'markdown', content: '卡片摘要' }] } });
    const preview = mount(FeishuReportPreviewContent, { props: {
      data: { title: '销售报表', summary: '旧长摘要', sections: ['旧分节内容'] }, card
    } });
    expect(preview.text()).toContain('销售报表');
    expect(preview.text()).toContain('卡片摘要');
    expect(preview.text()).not.toContain('旧长摘要');
    expect(preview.text()).not.toContain('旧分节内容');
    preview.unmount();
  });

  it('catalog未授权的dataset拒绝初始化，且只采用允许字段中的有效日期', () => {
    const datasets = [
      { id: 'sales', defaults: { dimensions: ['country'] }, filters: ['date_from', 'date_to'] },
      { id: 'refunds', defaults: {}, filters: ['date_from'] }
    ];
    expect(initializeFeishuReportConfig(datasets, { feishu_dataset: 'finance' }, () => ({}))).toBeNull();
    expect(initializeFeishuReportConfig(datasets, { feishu_dataset: 'refunds', date_from: '2026-10-01', date_to: '2026-10-31' }, () => ({}))).toMatchObject({
      dataset: 'refunds', filters: { date_from: '2026-10-01' }
    });
    expect(initializeFeishuReportConfig(datasets, { feishu_dataset: 'sales', date_from: '2026-02-30', date_to: '2026-10-31' }, () => ({})).filters).toEqual({ date_to: '2026-10-31' });
  });

  it('详情链接保留catalog允许且格式有效的日期、店铺、国家和币种过滤', () => {
    const datasets = [{ id: 'sales', filters: ['date_from', 'date_to', 'store_id', 'region', 'currency'] }];
    const query = {
      feishu_dataset: 'sales', date_from: '2026-10-01', date_to: '2026-10-31',
      store_id: '1234567890123456789', region: 'US', currency: 'USD'
    };
    expect(feishuReportLocation(datasets, query)?.query).toEqual({
      tab: 'analysis', feishu_dataset: 'sales', date_from: '2026-10-01', date_to: '2026-10-31',
      store_id: '1234567890123456789', region: 'US', currency: 'USD'
    });
    expect(initializeFeishuReportConfig(datasets, query, () => ({})).filters).toEqual({
      date_from: '2026-10-01', date_to: '2026-10-31', store_id: '1234567890123456789', region: 'US', currency: 'USD'
    });
  });

  it('拒绝未授权dataset、非catalog字段、身份参数及格式错误或非标量过滤值', () => {
    const datasets = [{ id: 'sales', filters: ['date_from', 'store_id', 'region', 'currency', 'token', 'tenant_id', 'user_id', 'ignored'] }];
    expect(feishuReportLocation(datasets, { feishu_dataset: 'finance', store_id: '1' })).toBeNull();
    expect(feishuReportLocation(datasets, {
      feishu_dataset: 'sales', date_from: '2026-10-01', arbitrary: 'x', ignored: 'x',
      token: 'secret', tenant_id: 'tenant', user_id: 'user',
      store_id: '１２', region: 'us', currency: 'US',
    })?.query).toEqual({ tab: 'analysis', feishu_dataset: 'sales', date_from: '2026-10-01' });
    for (const store_id of ['0', '-1', '1.0', '12345678901234567890', ['1'], { value: '1' }]) {
      expect(feishuReportLocation(datasets, { feishu_dataset: 'sales', store_id })?.query.store_id).toBeUndefined();
    }
    for (const [key, value] of [['region', 'USA1'], ['region', ['US']], ['currency', 'usd'], ['currency', { value: 'USD' }]]) {
      expect(feishuReportLocation(datasets, { feishu_dataset: 'sales', [key]: value })?.query[key]).toBeUndefined();
    }
  });
});
