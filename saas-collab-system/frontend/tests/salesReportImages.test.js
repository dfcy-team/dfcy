import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { mount } from '@vue/test-utils';
import { ElImage, ElTable, ElTableColumn } from 'element-plus';
import SalesReportTable from '../src/views/sales-management/SalesReportTable.vue';

describe('SalesReportTable product images', () => {
  it('keeps the reason image preview inside its native dialog', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/sales-management/SalesOperations.vue'), 'utf8');
    const reasonDialog = source.match(/<dialog ref="reasonDialog"[\s\S]*?<\/dialog>/)?.[0];

    expect(reasonDialog).toContain(':preview-teleported="false"');
  });

  it('renders platform image preview and distinct missing/ambiguous placeholders', async () => {
    const wrapper = mount(SalesReportTable, {
      props: { skuReport: true, rows: [
        { platform_image_url: 'https://img.example/item.jpg', image_status: 'available', product_name: 'Visible', seller_sku: 'A' },
        { platform_image_url: '', image_status: 'ambiguous', product_name: 'Ambiguous', seller_sku: 'B' },
        { platform_image_url: '', image_status: 'missing', product_name: 'Missing', seller_sku: 'C' },
      ] },
      global: { components: { ElImage, ElTable, ElTableColumn } },
    });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(wrapper.find('img.el-image__inner').attributes('src')).toBe('https://img.example/item.jpg');
    expect(wrapper.text()).toContain('多店铺/多规格');
    expect(wrapper.text()).toContain('暂无图片');
    wrapper.unmount();
  });
});
