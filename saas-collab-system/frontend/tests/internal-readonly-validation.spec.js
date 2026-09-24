import { describe, expect, it } from 'vitest';
import { internalReadonlyFieldErrors, validateSourceCidrs } from '../src/utils/internalReadonlyValidation';

describe('只读调用系统保存校验', () => {
  it('拒绝非网段起始地址并指出可用的网段地址', () => {
    expect(validateSourceCidrs(['10.20.0.0/16', '27.154.92.0/16']))
      .toContain('仅允许 27.154.92.* 请填 27.154.92.0/24；整个 /16 请填 27.154.0.0/16');
    expect(validateSourceCidrs(['10.20.0.0/16', '27.154.92.194/32', '27.154.92.0/24'])).toBe('');
    expect(validateSourceCidrs(['256.1.1.1'])).toContain('格式无效');
  });

  it('把服务端字段错误映射到明确字段', () => {
    expect(internalReadonlyFieldErrors({ data: { allowed_cidrs: ['Invalid canonical CIDR: host bits set'] } }))
      .toEqual({ allowed_cidrs: '来源 IP/CIDR：Invalid canonical CIDR: host bits set' });
    expect(internalReadonlyFieldErrors({ data: null })).toEqual({});
  });
});
