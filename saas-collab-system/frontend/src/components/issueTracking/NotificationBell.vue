<template>
  <el-badge :value="unreadCount" :max="99" :hidden="!loaded || unreadCount === 0" class="notification-badge">
    <el-button class="notification-bell" text :aria-label="buttonLabel" :title="buttonLabel" @click="showMessages">
      <svg aria-hidden="true" viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></svg>
    </el-button>
  </el-badge>
  <el-drawer v-model="open" title="我的消息" size="min(480px, 100vw)" append-to-body>
    <div class="message-toolbar">
      <span>事件跟踪通知 · {{loaded ? `${unreadCount} 条未读` : '正在获取未读数量'}}</span>
      <el-button text :disabled="!loaded || !unreadCount || reading" @click="markAll">全部标为已读</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-tabs v-model="mode" @tab-change="firstPage"><el-tab-pane label="未读消息" name="unread"/><el-tab-pane label="全部消息" name="all"/></el-tabs>
    <el-skeleton v-if="busy && !loaded" :rows="4" animated />
    <template v-else>
      <el-empty v-if="!items.length && !error" :description="mode === 'unread' ? '暂无未读消息' : '暂无消息'" />
      <div class="message-list" :aria-busy="busy">
        <button v-for="item in items" :key="item.id" class="message-item" :class="{'is-unread': !item.read_at}" :disabled="reading" @click="openMessage(item)">
          <strong><span v-if="!item.read_at" class="unread-dot" aria-label="未读" />{{item.issue_title || `事项 #${item.issue}`}}</strong>
          <span>{{actions[item.action] || eventLabels[item.action] || '事件更新'}}</span>
          <time :datetime="item.created_at">{{trackingTime(item.created_at)}}</time>
        </button>
      </div>
      <el-pagination v-if="total > 20" v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="refresh"/>
    </template>
    <template #footer><div class="message-footer"><el-button :loading="busy" @click="refresh">刷新</el-button><el-button type="primary" @click="openTracking()">查看全部事件跟踪</el-button></div></template>
  </el-drawer>
</template>
<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { tracking, actions } from '../../api/issueTracking';
import { eventLabels, trackingTime } from './display';
const unreadCount = ref(0), loaded = ref(false), open = ref(false), mode = ref('unread');
const items = ref([]), total = ref(0), page = ref(1), busy = ref(false), reading = ref(false), error = ref('');
const buttonLabel = computed(() => error.value ? '消息提醒，消息暂未更新' : loaded.value ? `消息提醒，${unreadCount.value} 条未读` : '消息提醒');
let alive = true, requestId = 0, timer;
async function refresh() {
  const id = ++requestId;
  busy.value = true;
  try {
    const result = await tracking('notification-center/', 'get', null, {view: mode.value, page: page.value, page_size: 20});
    if (!alive || id !== requestId) return;
    unreadCount.value = result.unread_count; items.value = result.results; total.value = result.count; page.value = result.page;
    loaded.value = true; error.value = '';
  } catch (e) {
    if (alive && id === requestId) error.value = e.message || '消息加载失败，请刷新重试';
  } finally { if (alive && id === requestId) busy.value = false; }
}
function firstPage() { page.value = 1; return refresh(); }
function showMessages() { open.value = true; firstPage(); }
function openTracking(issueId = '') {
  open.value = false;
  window.dispatchEvent(new CustomEvent('open-event-tracking', {detail: {issueId}}));
}
function changed() { window.dispatchEvent(new Event('issue-tracking-notifications-changed')); }
async function openMessage(item) {
  if (reading.value) return;
  reading.value = true;
  try {
    const result = await tracking('notification-center/', 'post', {id: item.id});
    unreadCount.value = result.unread_count;
    changed(); openTracking(item.issue);
  } catch (e) { error.value = e.message || '消息已不可访问，请刷新后重试'; }
  finally { reading.value = false; }
}
async function markAll() {
  if (reading.value) return;
  reading.value = true;
  try {
    const result = await tracking('notification-center/', 'post', {all: true});
    unreadCount.value = result.unread_count; page.value = 1; changed();
  } catch (e) { error.value = e.message || '标记已读失败，请重试'; }
  finally { reading.value = false; }
}
function whenVisible() { if (document.visibilityState !== 'hidden') refresh(); }
onMounted(() => {
  refresh();
  timer = window.setInterval(() => { if (document.visibilityState !== 'hidden' && !busy.value) refresh(); }, 30000);
  window.addEventListener('issue-tracking-notifications-changed', refresh);
  window.addEventListener('issue-tracking-updated', refresh);
  document.addEventListener('visibilitychange', whenVisible);
});
onBeforeUnmount(() => {
  alive = false; requestId += 1; window.clearInterval(timer);
  window.removeEventListener('issue-tracking-notifications-changed', refresh);
  window.removeEventListener('issue-tracking-updated', refresh);
  document.removeEventListener('visibilitychange', whenVisible);
});
</script>
<style scoped>
.notification-badge{margin:0 9px 0 4px;flex-shrink:0}.notification-bell{min-width:34px;padding:7px}.message-toolbar,.message-footer{display:flex;align-items:center;justify-content:space-between;gap:12px}.message-toolbar{font-size:13px;color:#64748b}.message-list{display:grid;gap:8px}.message-item{display:grid;gap:7px;width:100%;padding:14px;text-align:left;border:1px solid #e2e8f0;border-radius:8px;background:white;color:#334155;cursor:pointer}.message-item:hover{background:#f8fafc}.message-item:focus-visible{outline:2px solid #2563eb;outline-offset:2px}.message-item.is-unread{background:#eff6ff;border-color:#bfdbfe}.message-item span,.message-item time{font-size:12px}.message-item time{color:#64748b}.message-item strong{overflow-wrap:anywhere}.unread-dot{display:inline-block;width:7px;height:7px;margin-right:7px;border-radius:50%;background:#dc2626}.el-pagination{margin-top:16px}
</style>
