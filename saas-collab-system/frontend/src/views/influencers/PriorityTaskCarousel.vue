<template>
  <section class="priority-carousel" aria-labelledby="priority-title">
    <div class="heading">
      <h2 id="priority-title">重点建联任务</h2>
      <nav v-if="!error && pageCount > 1" aria-label="重点任务翻组">
        <button type="button" class="previous" aria-label="上一组重点任务" @click="move(-1)"><span aria-hidden="true"></span></button>
        <span>{{ position + 1 }} / {{ pageCount }}</span>
        <button type="button" class="next" aria-label="下一组重点任务" @click="move(1)"><span aria-hidden="true"></span></button>
      </nav>
    </div>
    <p v-if="error" role="status">未能加载重点任务，请刷新动态重试。</p>
    <ul v-else-if="visibleTasks.length" class="tasks" aria-live="polite">
      <li v-for="task in visibleTasks" :key="task.id" class="task">
        <span class="badge" :data-priority="task.priority">{{ task.priority === 'urgent' ? '紧急' : '高' }}</span>
        <strong>{{ task.task_no }}</strong>
        <span class="name" :title="task.task_name">{{ task.task_name || '—' }}</span>
      </li>
    </ul>
    <p v-else role="status">{{ loading ? '正在加载重点任务…' : '暂无紧急或高优先级任务' }}</p>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
const props = defineProps({
  groups: { type: Object, default: () => ({ urgent: [], high: [] }) },
  loading: Boolean,
  error: Boolean,
});
const cursor = ref(0);
const pageSize = 3;
const tasks = computed(() => ['urgent', 'high'].flatMap(priority => (props.groups[priority] || []).map(task => ({ ...task, priority }))));
const pageCount = computed(() => Math.ceil(tasks.value.length / pageSize));
const position = computed(() => Math.min(cursor.value, Math.max(0, pageCount.value - 1)));
const visibleTasks = computed(() => tasks.value.slice(position.value * pageSize, (position.value + 1) * pageSize));
watch(pageCount, () => { cursor.value = position.value; });
function move(delta) {
  if (pageCount.value > 1) cursor.value = (position.value + delta + pageCount.value) % pageCount.value;
}
</script>

<style scoped>
.priority-carousel { min-width: 0; background: white; border: 1px solid #dce5ef; border-radius: 12px; padding: 12px; }
.heading, nav, .task { display: flex; align-items: center; gap: 8px; }
.heading { justify-content: space-between; }
h2 { margin: 0; color: #155e50; font-size: 13px; }
nav { flex-shrink: 0; font-size: 12px; color: #64748b; }
button { background: #f5f8fc; color: #2459cf; border: 1px solid #dce5ef; border-radius: 5px; cursor: pointer; width: 26px; height: 26px; font-size: 18px; }
button { display: grid; place-items: center; }
button span { width: 0; height: 0; border-block: 4px solid transparent; }
.previous span { border-right: 6px solid currentColor; }
.next span { border-left: 6px solid currentColor; }
.tasks { list-style: none; padding: 0; margin: 5px 0 0; }
.task { font-size: 12px; min-height: 24px; animation: reveal .18s ease-out; }
.task strong, .badge { flex-shrink: 0; }
.name { min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.badge { min-width: 32px; text-align: center; padding: 2px 4px; color: #b45309; background: #fff7ed; border-radius: 4px; }
.badge[data-priority="urgent"] { color: #b42318; background: #fff1f0; }
p { color: #64748b; font-size: 12px; }
@keyframes reveal { from { opacity: .4; transform: translateX(8px); } to { opacity: 1; transform: translateX(0); } }
@media(prefers-reduced-motion:reduce) { .task { animation: none; } }
</style>
