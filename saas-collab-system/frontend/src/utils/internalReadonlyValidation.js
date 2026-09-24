const FIELD_LABELS = {
  name: '系统名称', caller_type: '调用方类型', resources: '允许数据块/字段',
  allowed_cidrs: '来源 IP/CIDR', rate_limit_per_minute: '每分钟限流',
  page_size_limit: '分页上限', expires_at: '凭据有效期', status: '状态',
};

export function validateSourceCidrs(values) {
  if (!Array.isArray(values) || !values.length) return '请至少填写一个来源 IP/CIDR';
  for (const [index, value] of values.entries()) {
    const label = `第 ${index + 1} 个来源 IP/CIDR`;
    if (typeof value !== 'string') return `${label}不是有效地址`;
    const parts = value.split('/');
    const octets = parts[0].split('.');
    const prefix = parts.length === 1 ? 32 : Number(parts[1]);
    if (parts.length > 2 || octets.length !== 4 || !Number.isInteger(prefix) || prefix < 0 || prefix > 32
      || (parts.length === 2 && !/^(?:0|[1-9]\d*)$/.test(parts[1]))
      || octets.some((part) => !/^(?:0|[1-9]\d*)$/.test(part) || Number(part) > 255)) {
      return `${label}格式无效，请填写 IPv4 地址或网段（如 10.20.0.0/16）`;
    }
    if (parts.length === 2) {
      const address = octets.reduce((number, octet) => ((number << 8) | Number(octet)) >>> 0, 0);
      const mask = prefix === 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0;
      const network = (address & mask) >>> 0;
      if (address !== network) {
        const canonical = [24, 16, 8, 0].map((shift) => (network >>> shift) & 255).join('.');
        const smallerScope = prefix < 24 && Number(octets[3]) === 0
          ? `仅允许 ${octets.slice(0, 3).join('.')}.* 请填 ${octets.join('.')}/24；`
          : '';
        return `${label}：${value} 不是网段起始地址。${smallerScope}整个 /${prefix} 请填 ${canonical}/${prefix}`;
      }
    }
  }
  return '';
}

export function internalReadonlyFieldErrors(response) {
  if (!response?.data || typeof response.data !== 'object' || Array.isArray(response.data)) return {};
  return Object.fromEntries(Object.entries(response.data).map(([field, value]) => {
    const message = Array.isArray(value) ? value.map(String).join('；') : String(value);
    return [field, `${FIELD_LABELS[field] || field}：${message}`];
  }));
}
