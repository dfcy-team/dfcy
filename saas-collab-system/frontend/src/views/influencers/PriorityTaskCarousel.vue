<template>
  <section class="priority-carousel" aria-labelledby="priority-title">
    <div class="heading">
      <h2 id="priority-title">重点建联任务</h2>
      <nav v-if="tasks.length > 1" aria-label="重点任务切换">
        <button type="button" aria-label="上一条重点任务" @click="move(-1)">‹</button>
        <span>{{ position + 1 }} / {{ tasks.length }}</span>
        <button type="button" aria-label="下一条重点任务" @click="move(1)">›</button>
      </nav>
    </div>
    <p v-if="error" role="status">未能加载重点任务，请刷新动态重试。</p>
    <div v-else-if="current" :key="current.id" class="task" aria-live="polite">
      <span class="badge" :data-priority="current.priority">{{ current.priority === 'urgent' ? '紧急' : '高' }}</span>
      <strong>{{ current.task_no }}</strong>
      <span class="name" :title="current.task_name">{{ current.task_name || '—' }}</span>
    </div>
    <p v-else role="status">{{ loading ? '正在加载重点任务…' : '暂无紧急或高优先级任务' }}</p>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue';
const props = defineProps({
  groups: { type: Object, default: () => ({ urgent: [], high: [] }) },
  loading: Boolean,
  error: Boolean,
});
const cursor = ref(0);
const tasks = computed(() => ['urgent', 'high'].flatMap(priority => (props.groups[priority] || []).map(task => ({ ...task, priority }))));
const position = computed(() => tasks.value.length ? cursor.value % tasks.value.length : 0);
const current = computed(() => tasks.value[position.value]);
function move(delta) {
  if (tasks.value.length) cursor.value = (position.value + delta + tasks.value.length) % tasks.value.length;
}
</script>

<style scoped>
.priority-carousel { min-width: 0; background: white; border: 1px solid #dce5ef; border-radius: 12px; padding: 12px; }
.heading, nav, .task { display: flex; align-items: center; gap: 8px; }
.heading { justify-content: space-between; }
h2 { margin: 0; color: #155e50; font-size: 13px; }
nav { flex-shrink: 0; font-size: 12px; color: #64748b; }
button { background: #f5f8fc; color: #2459cf; border: 1px solid #dce5ef; border-radius: 5px; cursor: pointer; width: 26px; height: 26px; font-size: 18px; }
.task { margin-top: 10px; font-size: 12px; min-height: 26px; animation: reveal .18s ease-out; }
.task strong, .badge { flex-shrink: 0; }
.name { min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.badge { padding: 2px 5px; color: #b45309; background: #fff7ed; border-radius: 4px; }
.badge[data-priority="urgent"] { color: #b42318; background: #fff1f0; }
p { color: #64748b; font-size: 12px; }
@keyframes reveal { from { opacity: .4; transform: translateX(8px); } to { opacity: 1; transform: translateX(0); } }
@media(prefers-reduced-motion:reduce) { .task { animation: none; } }
</style>
