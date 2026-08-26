import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '..');

describe('integration sync job detail', () => {
  it('keeps the original detail dimensions and linked destinations', () => {
    const page = fs.readFileSync(path.join(root, 'src/views/integrations/IntegrationWorkspace.vue'), 'utf8');

    expect(page).toContain('jobDetailItems');
    expect(page).toContain("label: '查询范围'");
    expect(page).toContain("label: '单次安全上限'");
    expect(page).toContain("label: '同步检查点'");
    expect(page).toContain("label: '数据写入表'");
    expect(page).toContain('viewJobRuns(activeJob)');
    expect(page).toContain('viewJobBusiness(activeJob)');
  });
});
