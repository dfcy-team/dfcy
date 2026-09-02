import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

import SpuCodeDisplay from '../src/components/SpuCodeDisplay.vue';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');

describe('SPU 类目编码展示', () => {
  it('只拆分正式纯数字编码，并突出显示类目编码前缀', () => {
    const wrapper = mount(SpuCodeDisplay, { props: { code: '101010004' } });

    expect(wrapper.find('.spu-code-display__category').text()).toBe('10101');
    expect(wrapper.find('.spu-code-display__tail').text()).toBe('0004');
    expect(wrapper.find('.spu-code-display__category').attributes('title')).toContain('类目编码');
    expect(wrapper.attributes('aria-label')).toContain('类目编码：10101');
  });

  it('旧编码、非数字编码和空值原样/按占位符显示，不错误拆分', () => {
    for (const [code, expected] of [['HY071', 'HY071'], ['10101-0004', '10101-0004'], ['', '-']]) {
      const wrapper = mount(SpuCodeDisplay, { props: { code } });
      expect(wrapper.text()).toBe(expected);
      expect(wrapper.find('.spu-code-display__category').exists()).toBe(false);
    }
  });

  it('两个商品页面均接入同一展示组件，且只处理新 SPU', () => {
    const master = read('src/views/products/ProductMasterList.vue');
    const detail = read('src/views/products/ProductDetailData.vue');

    expect(master).toContain("import SpuCodeDisplay from '../../components/SpuCodeDisplay.vue';");
    expect(master).toContain('<SpuCodeDisplay :code="row.spu_code" />');
    expect(detail).toContain("import SpuCodeDisplay from '../../components/SpuCodeDisplay.vue';");
    expect(detail).toContain('<SpuCodeDisplay :code="row.spu_code" />');
    expect(detail).toContain('<SpuCodeDisplay :code="selectedRow.spu_code" placeholder="待生成" />');
    expect(detail).toContain('label="旧 SPU 编码"');
    expect(detail).not.toContain('<SpuCodeDisplay :code="row.legacy_spu_code"');
  });
});
