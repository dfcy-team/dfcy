export function tiktokTokenFailure(response) {
  const diagnostic = response?.data?.diagnostic;
  if (diagnostic?.platform !== 'tiktok' || diagnostic.stage !== 'exchange_token'
      || !/^[a-f0-9]{32}$/.test(diagnostic.diagnostic_id || '')) return null;
  let message;
  if (diagnostic.platform_error_code === '36004004'
      && ['platform_error', 'authentication_rejected'].includes(diagnostic.category)) {
    message = 'TikTok 拒绝了这枚授权码（36004004）：已使用、已过期或无效。请从当前店铺重新发起授权，使用新回调 URL；同一授权码不要在 dfcy 旧站和 SaaS 重复兑换。本次未保存新授权。';
  } else if (['timeout_uncertain', 'network_uncertain'].includes(diagnostic.category)) {
    message = 'TikTok 令牌请求网络超时或中断，结果尚不能确认，系统未自动重试。请先核对店铺授权时间与状态；需要重试时须重新发起授权，不要重复提交这条回调 URL。';
  } else return null;
  return { type: 'warning', message: `${message} 诊断编号：${diagnostic.diagnostic_id}。` };
}
