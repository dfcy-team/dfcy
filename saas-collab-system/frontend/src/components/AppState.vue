<template>
  <section class="app-state" :class="`app-state--${status}`" role="status" aria-live="polite">
    <el-result :icon="config.icon" :title="title || config.title" :sub-title="detail || config.detail">
      <template v-if="actionLabel || config.action" #extra>
        <el-button :type="config.buttonType" @click="$emit('action')">
          {{ actionLabel || config.action }}
        </el-button>
      </template>
    </el-result>
  </section>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  status: { type: String, default: 'empty' },
  title: { type: String, default: '' },
  detail: { type: String, default: '' },
  actionLabel: { type: String, default: '' }
});

defineEmits(['action']);

const states = {
  loading: { icon: 'info', title: '正在加载', detail: '正在获取最新数据，请稍候。', action: '', buttonType: 'primary' },
  empty: { icon: 'info', title: '暂无数据', detail: '当前筛选条件下没有可显示的数据。', action: '重置筛选', buttonType: 'default' },
  error: { icon: 'error', title: '加载失败', detail: '请求未完成，请检查网络后重试。', action: '重试', buttonType: 'primary' },
  forbidden: { icon: 'warning', title: '无权访问', detail: '当前角色、租户或数据范围不允许访问此内容。', action: '返回工作台', buttonType: 'default' },
  conflict: { icon: 'warning', title: '状态已变化', detail: '数据可能已被处理，请刷新后再操作。', action: '刷新状态', buttonType: 'primary' },
  invalid: { icon: 'warning', title: '信息未通过校验', detail: '请根据提示修正字段或业务条件。', action: '', buttonType: 'primary' },
  partial: { icon: 'warning', title: '部分完成', detail: '部分项目处理失败，请查看结果并重试失败项。', action: '查看失败项', buttonType: 'default' },
  offline: { icon: 'error', title: '服务暂不可用', detail: '已保留当前页面状态，恢复连接后可重试。', action: '重新连接', buttonType: 'primary' }
};

const config = computed(() => states[props.status] || states.error);
</script>

<style scoped>
.app-state {
  min-height: 220px;
  border: 1px solid #dbe3ec;
  border-radius: 8px;
  background: #fff;
}

.app-state :deep(.el-result) {
  padding: 28px 20px;
}
</style>
