import html2canvas from 'html2canvas';
const EXCLUDED = 'input,textarea,select,button,nav,script,style,[hidden],[aria-hidden="true"],[data-tracking-private],.main-scroll-controls,.tracking-float,.el-overlay,.el-drawer,.el-dialog,.el-popper';
export function workspace() {
  const el = document.querySelector('#workspace-content');
  if (!el) throw new Error('当前页面尚未就绪');
  return el;
}
export function isVisibleBusinessElement(el, root = workspace()) {
  if (!el || el.closest(EXCLUDED)) return false;
  for (let node = el; node; node = node.parentElement) {
    const style = getComputedStyle(node);
    if (style.display === 'none' || ['hidden', 'collapse'].includes(style.visibility) || style.opacity === '0' || style.contentVisibility === 'hidden') return false;
    if (node === root) break;
  }
  const box = el.getBoundingClientRect(), area = root.getBoundingClientRect();
  return box.width > 0 && box.height > 0 && box.right > Math.max(0, area.left) && box.left < Math.min(innerWidth, area.right) && box.bottom > Math.max(0, area.top) && box.top < Math.min(innerHeight, area.bottom);
}
export function visibleDetails(root = workspace()) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const parts = []; let node; let length = 0;
  while ((node = walker.nextNode()) && length < 12000) {
    const text = node.textContent.replace(/\s+/g, ' ').trim();
    if (text && isVisibleBusinessElement(node.parentElement, root)) { parts.push(text); length += text.length + 1; }
  }
  const result = parts.join('\n').slice(0, 12000);
  if (!result) throw new Error('当前没有可采集的可见明细，请先展开需要跟踪的业务内容');
  return result;
}
export async function captureWorkspace() {
  const root = workspace(), area = root.getBoundingClientRect();
  if (!area.width || !area.height) throw new Error('当前页面不可截图，请先打开业务页面');
  const canvas = await html2canvas(root, {
    logging: false, scale: 1, useCORS: true, allowTaint: false,
    width: Math.min(root.clientWidth, innerWidth), height: Math.min(root.clientHeight, innerHeight),
    ignoreElements: el => el !== root && (Boolean(el.closest(EXCLUDED)) || !isVisibleBusinessElement(el, root)),
  });
  const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
  if (!blob || !blob.size) throw new Error('截图失败，请改用页面明细或本地图片');
  return blob;
}
