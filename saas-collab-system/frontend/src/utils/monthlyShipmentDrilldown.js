export function openMonthlyShipment(shipmentId, month) {
  const dialog = document.createElement('dialog');
  dialog.setAttribute('aria-label', '月份对账 · 供应商发货单详情');
  dialog.style.cssText = 'position:fixed;inset:0;margin:0;border:0;padding:0;width:100vw;height:100dvh;max-width:none;max-height:none;background:white';
  const frame = document.createElement('iframe');
  frame.title = '供应商发货单详情';
  frame.style.cssText = 'display:block;width:100%;height:100%;border:0';
  const params = new URLSearchParams({shipment_id: shipmentId, month});
  frame.src = '/monthly-shipment-detail/?' + params;
  const originFocus = document.activeElement;
  function closeFromFrame(event) {
    if (event.origin === location.origin && event.source === frame.contentWindow &&
        event.data?.type === 'close-monthly-shipment') dialog.close();
  }
  function onEscape(event) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      dialog.close();
    }
  }
  window.addEventListener('message', closeFromFrame);
  frame.addEventListener('load', () => {
    try { frame.contentWindow.addEventListener('keydown', onEscape); } catch { /* cross-origin link */ }
  });
  dialog.addEventListener('close', () => {
    window.removeEventListener('message', closeFromFrame);
    dialog.remove();
    originFocus?.focus({preventScroll:true});
  }, {once:true});
  dialog.append(frame);
  document.body.append(dialog);
  dialog.showModal();
  frame.focus();
}
