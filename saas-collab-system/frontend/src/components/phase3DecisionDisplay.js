export function decisionStatusLabel(value) {
  return ({
    suggested: '待复核', pending: '待处理', confirmed: '已确认', rejected: '已拒绝',
    open: '待处理', assigned: '已分派', acknowledged: '已确认', in_progress: '处理中',
    silenced: '已静默', resolved: '已解决', closed: '已关闭', ignored: '已忽略',
    high: '高', critical: '严重', medium: '中', low: '低', good: '正常',
    connected: '已连接', fallback: '已回退', degraded: '降级运行', mock: '演示数据',
  })[value] || value || '--';
}

export function decisionTableEmptyText(errorMessage, emptyText) {
  return errorMessage ? '数据读取失败，请查看上方错误信息。' : emptyText;
}
