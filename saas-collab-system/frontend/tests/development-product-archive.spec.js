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

  it('keeps mock lifecycle states virtual until explicit actions', () => {
    const api = read('src/api/development.js');
    expect(api).toContain("status: 'trial'");
    expect(api).toContain("status: 'confirmed'");
    expect(api).toContain("status: 'formalized'");
    expect(api).toContain('archiveConfirmMock');
    expect(api).toContain('archiveFormalizeMock');
  });

  it('keeps the archive page inside the product development module', () => {
    const page = read('src/views/development/DevelopmentProductArchiveList.vue');
    const router = read('src/router/menu.js');
    expect(page).toContain('开发产品档案');
    expect(page).toContain('confirmDevelopmentProductArchive');
    expect(page).toContain('formalizeDevelopmentProductArchive');
    expect(page).toContain('不会发布到外部平台');
    expect(router).toContain('/development/projects/archives');
  });
});
