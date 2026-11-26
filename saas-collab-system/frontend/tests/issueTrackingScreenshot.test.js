import { mount, flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ScreenshotEditor from '../src/components/issueTracking/ScreenshotEditor.vue';

let draw, fill, stroke, decode;
const button = { template: '<button @click="$emit(\'click\')"><slot /></button>' };
function editor() { return mount(ScreenshotEditor, { global: { stubs: { ElButton: button, ElRadioGroup: { template: '<div><slot /></div>' }, ElRadioButton: { template: '<span><slot /></span>' } } } }); }
async function choose(wrapper, type = 'image/png') {
  const input = wrapper.find('input');
  Object.defineProperty(input.element, 'files', { configurable: true, value: [new File(['image'], 'image.png', { type })] });
  await input.trigger('change'); await flushPromises();
}
beforeEach(() => {
  draw = vi.fn(); fill = vi.fn(); stroke = vi.fn(); decode = vi.fn().mockResolvedValue();
  vi.stubGlobal('Image', class { width = 800; height = 600; decode = decode; });
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() });
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ clearRect: vi.fn(), drawImage: draw, fillRect: fill, strokeRect: stroke });
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (callback) { callback(new Blob(['flattened'], { type: 'image/png' })); });
  HTMLCanvasElement.prototype.setPointerCapture = vi.fn();
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
describe('事项截图提交边界', () => {
  it('拒绝非图片且不会生成附件', async () => {
    const w = editor(); await choose(w, 'text/html');
    expect(w.get('[role="alert"]').text()).toContain('请选择');
    expect(w.find('canvas').exists()).toBe(false); expect(w.emitted('confirmed')).toBeUndefined(); w.unmount();
  });
  it('加载图片后需要明确确认；确认产生扁平化PNG，修改后清除旧附件', async () => {
    const w = editor(); await choose(w);
    expect(w.emitted('confirmed').at(-1)).toEqual([null]);
    await w.findAll('button').find(x => x.text() === '确认截图').trigger('click');
    const file = w.emitted('confirmed').at(-1)[0]; expect(file).toBeInstanceOf(File); expect(file.type).toBe('image/png');
    await w.findAll('button').find(x => x.text() === '撤销标注').trigger('click');
    expect(w.emitted('confirmed').at(-1)).toEqual([null]); w.unmount();
  });
  it('遮挡写入图片像素，裁剪按选区输出', async () => {
    const w = editor(); await choose(w);
    const c = w.get('canvas');
    vi.spyOn(c.element, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 800, height: 600 });
    w.vm.mode = 'redact';
    await c.trigger('pointerdown', { clientX: 10, clientY: 20, pointerId: 1 });
    await c.trigger('pointerup', { clientX: 110, clientY: 100, pointerId: 1 });
    expect(fill).toHaveBeenCalledWith(10, 20, 100, 80);
    w.vm.mode = 'crop';
    await c.trigger('pointerdown', { clientX: 0, clientY: 0, pointerId: 1 });
    await c.trigger('pointerup', { clientX: 200, clientY: 150, pointerId: 1 });
    expect(w.vm.cropRegion.w).toBe(200);
    await w.findAll('button').find(x => x.text() === '应用裁剪').trigger('click'); await flushPromises();
    expect(draw.mock.calls.some(args => args.length === 9 && args[3] === 200 && args[4] === 150)).toBe(true);
    expect(w.vm.cropRegion).toBe(null); w.unmount();
  });
  it('解码失败时展示错误并释放临时URL', async () => {
    decode.mockRejectedValueOnce(new Error('无法解码图片')); const w = editor(); await choose(w);
    expect(w.get('[role="alert"]').text()).toContain('无法解码'); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test'); w.unmount();
  });
});
