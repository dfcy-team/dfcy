import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');

describe('development product archive lifecycle', () => {
  it('exposes the tenant archive API and explicit lifecycle actions', () => {
    const api = read('src/api/development.js');
    expect(api).toContain("/api/internal/development/product-archives/");
    expect(api).toContain("confirm-trial/");
    expect(api).toContain("formalize/");
    expect(api).toContain('export const fetchDevelopmentProductArchives');
    expect(api).toContain('export const formalizeDevelopmentProductArchive');
  });

  it('uses the real tenant API without a mock fallback in production code', () => {
    const api = read('src/api/development.js');
    expect(api).toContain("method: 'get'");
    expect(api).toContain("method: 'post'");
    expect(api).toContain("method: 'patch'");
    expect(api).not.toContain('archiveConfirmMock');
    expect(api).not.toContain('archiveFormalizeMock');
  });

  it('keeps the archive page inside the product development module', () => {
    const page = read('src/views/development/DevelopmentProductArchiveList.vue');
    const router = read('src/router/menu.js');
    expect(page).toContain('开发产品档案');
    expect(page).toContain('confirmDevelopmentProductArchive');
    expect(page).toContain('formalizeDevelopmentProductArchive');
    expect(page).toContain('不会发布到外部平台');
    expect(page).toContain('虚拟库存测品通过后先进入上新计划');
    expect(page).toContain('实际小单测款达标可直接转正');
    expect(page).toContain('trial_mode');
    expect(router).toContain('/development/projects/archives');
  });

  it('uses tenant master-data dropdowns and the idempotent trial-product action', () => {
    const page = read('src/views/development/DevelopmentProductArchiveList.vue');
    const api = read('src/api/development.js');
    expect(page).toContain('fetchPlatforms');
    expect(page).toContain('fetchCountrySites');
    expect(page).toContain('fetchStores');
    expect(page).toContain('fetchProductColors');
    expect(page).toContain('fetchAllOptions');
    expect(page).toContain('page_size: 100');
    expect(page).not.toContain('page_size: 500');
    expect(page).toContain('@change="onPlatformChange"');
    expect(page).toContain('form.store_master = null');
    expect(page).toContain('spec_values: { ...trialForm.spec_values }');
    expect(page).toContain('development_spu_code');
    expect(page).toContain('三段 = 人工开发 SPU - 颜色 - 规格');
    expect(page).toContain("'STD'");
    expect(page).toContain('developmentSkuPreview');
    expect(page).toContain('按正式规则生成另一套正式 SPU/SKU');
    expect(page).toContain('正式 SPU / SKU');
    expect(page).toContain('生成测品 SPU/SKU');
    expect(api).toContain('generateDevelopmentProductArchiveTrial');
    expect(api).toContain('generate-trial/');
  });

  it('submits development project primary keys and omits nullable master-data ids', () => {
    const page = read('src/views/development/DevelopmentProductArchiveList.vue');
    expect(page).toContain('fetchDevelopmentProjects');
    expect(page).toContain('placeholder="选择开发项目"');
    expect(page).toContain(':value="Number(project.id)"');
    expect(page).toContain('project: projectId');
    expect(page).not.toContain('project: Number(form.project)');
    expect(page).toContain('if (platformId !== null) payload.platform_master = platformId;');
    expect(page).toContain('if (storeId !== null) payload.store_master = storeId;');
    expect(page).toContain('formatArchiveError(response, \'档案保存失败\')');
    expect(page).toContain("project: '开发项目'");
    expect(page).toContain('不能为空');
    expect(page).toContain('L2 或 L3 商品分类');
  });
});
