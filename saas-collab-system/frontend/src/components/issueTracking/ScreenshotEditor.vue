<template>
  <section class="capture-editor">
    <label>添加截图 <input type="file" accept="image/png,image/jpeg,image/webp" @change="loadFile" /></label>
    <el-button :disabled="busy" @click="capture">截取屏幕</el-button>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="source">
      <div class="tools">
        <el-radio-group v-model="mode"><el-radio-button value="mark">圈选标注</el-radio-button><el-radio-button value="redact">遮挡内容</el-radio-button><el-radio-button value="crop">裁剪区域</el-radio-button></el-radio-group>
        <el-button @click="undo">撤销标注</el-button><el-button :disabled="!cropRegion" @click="crop">应用裁剪</el-button><el-button @click="clear">移除截图</el-button>
      </div>
      <canvas ref="canvas" aria-label="截图标注区域，拖动绘制圈选或遮挡" @pointerdown="start" @pointermove="move" @pointerup="finish" @pointercancel="cancel" />
      <p>请检查截图中的敏感内容，遮挡后再确认。仅确认后的图片会交给事项表单。</p>
      <el-button type="primary" :loading="exporting" @click="confirm">{{confirmed ? '截图已确认' : '确认截图'}}</el-button>
    </template>
  </section>
</template>
<script setup>
import { computed, nextTick, ref, onBeforeUnmount } from 'vue';
const emit = defineEmits(['confirmed']);
const cropRegion = ref(null), confirmed = ref(false), exporting = ref(false);
defineExpose({ hasUnconfirmed: computed(() => Boolean(source.value && !confirmed.value)) });
const canvas = ref(null), source = ref(null), mode = ref('mark'), error = ref(''), busy = ref(false);
let revision = 0;
let image = null, origin = null, preview = null, shapes = [], stream = null;
function draw() {
  if (!canvas.value || !image) return;
  const ctx = canvas.value.getContext('2d');
  ctx.clearRect(0, 0, canvas.value.width, canvas.value.height); ctx.drawImage(image, 0, 0);
  for (const item of [...shapes, ...(cropRegion.value ? [{ ...cropRegion.value, mode: 'crop' }] : []), ...(preview ? [preview] : [])]) {
    if (item.mode === 'redact') { ctx.fillStyle = '#111827'; ctx.fillRect(item.x, item.y, item.w, item.h); }
    else { ctx.strokeStyle = item.mode === 'crop' ? '#2563eb' : '#dc2626'; ctx.lineWidth = Math.max(3, image.width / 400); ctx.strokeRect(item.x, item.y, item.w, item.h); }
  }
}
async function setImage(blob) {
  if (blob.size > 10 * 1024 * 1024) throw new Error('截图不能超过10MB');
  const url = URL.createObjectURL(blob);
  try {
    const next = new Image(); next.src = url; await next.decode();
    if (next.width * next.height > 24000000) throw new Error('图片分辨率过大，请裁剪后重试');
    image = next; source.value = true; shapes = []; preview = null; cropRegion.value = null; revision += 1; confirmed.value = false; emit('confirmed', null);
    await nextTick(); canvas.value.width = next.width; canvas.value.height = next.height; draw();
  } finally { URL.revokeObjectURL(url); }
}
async function loadFile(event) {
  error.value = ''; const file = event.target.files?.[0]; event.target.value = '';
  if (!file) return;
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) { error.value = '请选择 PNG、JPEG 或 WebP 图片'; return; }
  try { await setImage(file); } catch (e) { error.value = e.message; }
}
async function capture() {
  error.value = ''; busy.value = true;
  try {
    if (!navigator.mediaDevices?.getDisplayMedia) throw new Error('当前环境不支持截屏，请使用系统截图后选择图片');
    stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    const video = document.createElement('video'); video.srcObject = stream; await video.play();
    await new Promise(resolve => requestAnimationFrame(resolve));
    const frame = document.createElement('canvas'); frame.width = video.videoWidth; frame.height = video.videoHeight;
    frame.getContext('2d').drawImage(video, 0, 0);
    const blob = await new Promise(resolve => frame.toBlob(resolve, 'image/png'));
    if (!blob) throw new Error('未能读取截图，请重试');
    await setImage(blob);
  } catch (e) { error.value = e.name === 'NotAllowedError' ? '已取消截屏，可选择本地截图' : e.message; }
  finally { stream?.getTracks().forEach(track => track.stop()); stream = null; busy.value = false; }
}
function point(e) { const box = canvas.value.getBoundingClientRect(); return { x: Math.max(0, Math.min(canvas.value.width, (e.clientX - box.left) * canvas.value.width / box.width)), y: Math.max(0, Math.min(canvas.value.height, (e.clientY - box.top) * canvas.value.height / box.height)) }; }
function start(e) { revision += 1; confirmed.value = false; emit('confirmed', null); origin = point(e); canvas.value.setPointerCapture(e.pointerId); }
function move(e) { if (!origin) return; const p = point(e); preview = { mode: mode.value, x: Math.min(origin.x, p.x), y: Math.min(origin.y, p.y), w: Math.abs(p.x - origin.x), h: Math.abs(p.y - origin.y) }; draw(); }
function finish(e) { if (!origin) return; move(e); if (preview?.w > 2 && preview?.h > 2) { if (preview.mode === 'crop') cropRegion.value = preview; else shapes.push(preview); } origin = null; preview = null; draw(); }
function cancel() { origin = null; preview = null; draw(); }
function undo() { revision += 1; confirmed.value = false; emit('confirmed', null); shapes.pop(); preview = null; draw(); }
async function crop() {
  const region = cropRegion.value; if (!region) return;
  cropRegion.value = null; preview = null; draw();
  const result = document.createElement('canvas'); result.width = Math.max(1, Math.round(region.w)); result.height = Math.max(1, Math.round(region.h));
  result.getContext('2d').drawImage(canvas.value, region.x, region.y, region.w, region.h, 0, 0, result.width, result.height);
  const blob = await new Promise(resolve => result.toBlob(resolve, 'image/png'));
  if (blob) await setImage(blob);
}
function clear() { source.value = null; cropRegion.value = null; image = null; shapes = []; origin = null; preview = null; revision += 1; confirmed.value = false; emit('confirmed', null); }
function confirm() { exporting.value = true; cropRegion.value = null; preview = null; draw(); const version = revision; canvas.value.toBlob(blob => { exporting.value = false; if (blob && version === revision) { confirmed.value = true; emit('confirmed', new File([blob], 'tracking-screenshot.png', { type: 'image/png' })); } }, 'image/png'); }
onBeforeUnmount(() => stream?.getTracks().forEach(track => track.stop()));
</script>
<style scoped>
.capture-editor { display: grid; gap: 12px; } canvas { max-width: 100%; border: 1px solid #cbd5e1; touch-action: none; cursor: crosshair; } .tools { display: flex; flex-wrap: wrap; gap: 8px; } p { color: #64748b; font-size: 13px; margin: 0; }
</style>
