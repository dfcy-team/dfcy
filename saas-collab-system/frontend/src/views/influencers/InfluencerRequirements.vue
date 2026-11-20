<template>
  <main class="requirement-desk">
    <header>
      <small>达人管理</small>
      <h1>达人模块需求反馈</h1>
      <p>请描述使用场景、遇到的问题和期望结果。不要填写密码、令牌或客户隐私。</p>
    </header>
    <form v-if="allowed" @submit="submit" @paste="pasteImages">
      <h2>提交需求</h2>
      <label>需求标题<input :value="title" @input="title = $event.target.value" required maxlength="120" placeholder="例如：送样列表希望支持按仓库筛选" /></label>
      <label>需求说明<textarea :value="description" @input="description = $event.target.value" required maxlength="3000" rows="5" /></label>
      <label>补充图片<input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp" multiple :disabled="saving" @change="selectImages" /></label>
      <div class="paste-images" tabindex="0" role="group" aria-label="粘贴图片">点击此处，按 Ctrl+V 或 ⌘+V 粘贴截图</div>
      <small>最多 3 张，每张不超过 2 MB。请遮挡密码、令牌和客户隐私。</small>
      <div class="images">
        <figure v-for="(image, index) in selectedImages" :key="image.url">
          <a :href="image.url" target="_blank" rel="noopener"><img :src="image.url" alt="待提交图片预览" /></a>
          <button type="button" :disabled="saving" @click="removeImage(index)">移除</button>
        </figure>
      </div>
      <button type="submit" :disabled="saving || !title.trim() || !description.trim()">{{ saving ? '提交中…' : '提交需求' }}</button>
    </form>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <section v-if="allowed" :aria-busy="loading">
      <h2>{{ canReview ? '需求汇总' : '我的需求' }}</h2>
      <p v-if="!rows.length && !loading">暂无需求。</p>
      <article v-for="row in rows" :key="row.id">
        <h3>{{ row.title }}</h3>
        <small>#{{ row.id }} · {{ row.author__username }} · {{ time(row.created_at) }}</small>
        <p>{{ row.description }}</p>
        <button v-if="row.image_ids?.length" type="button" :disabled="imageLoading === row.id" @click="showImages(row)">查看图片（{{ row.image_ids.length }}）</button>
        <div class="images">
          <a v-for="image in displayedImages[row.id] || []" :key="image" :href="image" target="_blank" rel="noopener"><img :src="image" alt="需求反馈附件，点击查看大图" /></a>
        </div>
      </article>
      <nav v-if="count > 20" aria-label="需求分页">
        <button :disabled="loading || page <= 1" @click="load(page - 1)">上一页</button>
        <span>第 {{ page }} 页 · 共 {{ count }} 条</span>
        <button :disabled="loading || page * 20 >= count" @click="load(page + 1)">下一页</button>
      </nav>
    </section>
  </main>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue';
import { requestApi, fetchApiFile } from '../../api/request';

const url = '/api/internal/influencers/requirements/';
const title = ref('');
const description = ref('');
const allowed = ref(false);
const canReview = ref(false);
const rows = ref([]);
const page = ref(1);
const count = ref(0);
const error = ref('');
const notice = ref('');
const loading = ref(false);
const saving = ref(false);
const selectedImages = ref([]);
const displayedImages = ref({});
const imageLoading = ref(null);
const fileInput = ref(null);
const allocatedUrls = new Set();
const objectUrl = file => {
  const value = URL.createObjectURL(file);
  allocatedUrls.add(value);
  return value;
};
function removeImage(index) {
  const [image] = selectedImages.value.splice(index, 1);
  URL.revokeObjectURL(image.url);
  allocatedUrls.delete(image.url);
}
function selectImages(event) {
  const files = [...event.target.files];
  event.target.value = '';
  addImages(files);
}
function pasteImages(event) {
  const clipboard = event.clipboardData;
  if (!clipboard) return;
  const files = Array.from(clipboard.files || []).filter(file => file.type.startsWith('image/'));
  if (!files.length) {
    for (const item of Array.from(clipboard.items || [])) {
      if (item.kind !== 'file' || !item.type.startsWith('image/')) continue;
      const file = item.getAsFile();
      if (file) files.push(file);
    }
  }
  if (!files.length) return;
  event.preventDefault();
  addImages(files);
}
function addImages(files) {
  if (saving.value || !files.length) return;
  if (selectedImages.value.length + files.length > 3 || files.some(file => file.size > 2 * 1024 * 1024 || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type))) {
    error.value = '最多选择 3 张 JPG、PNG 或 WebP 图片，每张不超过 2 MB。';
    return;
  }
  error.value = '';
  selectedImages.value.push(...files.map(file => ({ file, url: objectUrl(file) })));
}
async function showImages(row) {
  if (imageLoading.value || displayedImages.value[row.id]) return;
  imageLoading.value = row.id;
  const loaded = [];
  try {
    for (const id of row.image_ids) {
      const response = await fetchApiFile(`${url}${row.id}/images/${id}/`);
      if (!response.success) throw new Error('image unavailable');
      loaded.push(objectUrl(response.blob));
    }
    displayedImages.value[row.id] = loaded;
  } catch {
    for (const value of loaded) { URL.revokeObjectURL(value); allocatedUrls.delete(value); }
    error.value = '图片加载失败，请重试。';
  } finally { imageLoading.value = null; }
}
onUnmounted(() => { for (const value of allocatedUrls) URL.revokeObjectURL(value); });
const formatter = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'medium', timeStyle: 'short' });
const time = value => formatter.format(new Date(value));

async function load(next = 1) {
  loading.value = true;
  error.value = '';
  try {
    const result = await requestApi({ method: 'get', url, params: { page: next } });
    if (!result.success) {
      allowed.value = false;
      error.value = result.http_status === 403 ? '当前账号没有需求反馈权限。' : '需求加载失败，请刷新重试。';
      return;
    }
    allowed.value = true;
    canReview.value = result.data.can_review;
    rows.value = result.data.results;
    page.value = result.data.page;
    count.value = result.data.count;
  } catch {
    error.value = '需求加载失败，请刷新重试。';
  } finally {
    loading.value = false;
  }
}

async function submit(event) {
  event.preventDefault();
  if (saving.value || !title.value.trim() || !description.value.trim()) return;
  saving.value = true;
  error.value = '';
  notice.value = '';
  try {
    const data = new FormData();
    data.append('title', title.value);
    data.append('description', description.value);
    for (const image of selectedImages.value) data.append('images', image.file);
    const result = await requestApi({ method: 'post', url, data });
    if (!result.success) {
      error.value = '未能确认提交结果，请先刷新需求列表核对，再决定是否重试。';
      return;
    }
    title.value = '';
    description.value = '';
    while (selectedImages.value.length) removeImage(0);
    notice.value = '需求已提交。';
    await load();
  } catch {
    error.value = '未能确认提交结果，请先刷新需求列表核对，再决定是否重试。';
  } finally {
    saving.value = false;
  }
}
onMounted(() => load());
</script>

<style scoped>
.requirement-desk { display: grid; gap: 16px; }
header, form, section { padding: 20px; background: white; border: 1px solid #dce5ef; border-radius: 12px; }
header { background: linear-gradient(115deg, #103d35, #176e5c); color: white; }
h1, h2, h3 { margin: 0 0 8px; }
form, label { display: grid; gap: 8px; }
input, textarea { width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; font: inherit; }
button { width: fit-content; padding: 6px 12px; color: white; background: #2459cf; border: 0; border-radius: 6px; cursor: pointer; }
button:disabled { opacity: .55; cursor: default; }
article { border-top: 1px solid #dce5ef; padding: 12px 0; overflow-wrap: anywhere; }
article p { white-space: pre-wrap; }
nav { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.images { display: flex; flex-wrap: wrap; gap: 10px; }
.paste-images { padding: 8px 12px; border: 1px dashed #94a3b8; border-radius: 6px; color: #334155; background: #f8fafc; }
.paste-images:focus { outline: 2px solid #2459cf; outline-offset: 2px; }
.images figure { display: grid; gap: 4px; margin: 0; }
.images img { width: 128px; height: 96px; object-fit: contain; border: 1px solid #dce5ef; border-radius: 6px; }
[role="alert"] { color: #b42318; }
</style>
