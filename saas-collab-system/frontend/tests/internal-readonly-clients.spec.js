import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { mockCreateInternalReadonlyClient, mockInternalReadonlyClients, mockRotateInternalReadonlyCredential } from '../src/mock/internalReadonly';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');

describe('内部系统只读调用方配置', () => {
  it('使用统一后端端点并为轮换传递幂等键', () => {
    const api = read('src/api/internalReadonly.js');
    expect(api).toContain("'/api/internal/integrations/internal-api-clients/'");
    expect(api).toContain("'Idempotency-Key': idempotencyKey");
    expect(api).toContain('/status/'); expect(api).toContain('/rotate/'); expect(api).toContain('audit/');
  });

  it('创建和轮换仅在响应中返回一次性密钥，列表不泄露', () => {
    const created = mockCreateInternalReadonlyClient({ name: '测试系统', resources: ['products'], fields: ['resource_id'] });
    expect(created.data.client_secret).toContain('only_once');
    expect(JSON.stringify(mockInternalReadonlyClients().data.items)).not.toContain('client_secret');
    expect(mockRotateInternalReadonlyCredential(created.data.id).data.client_secret).toContain('only_once');
  });

  it('页面提供完整配置闭环并保留只读与未上线声明', () => {
    const page = read('src/views/integrations/AIExternalApiSettings.vue');
    for (const text of ['新增调用系统','编辑','停用','轮换密钥','调用审计','一次性凭据','二次确认','强制只读']) expect(page).toContain(text);
    for (const field of ['name','caller_type','resources','fields','cidrs','rate_limit','page_size','expires_at']) expect(page).toContain(field);
    expect(page).toContain('/api/internal-readonly/v1/ 尚未上线');
    expect(page).toContain('@closed="oneTimeCredential=null"');
  });
});
