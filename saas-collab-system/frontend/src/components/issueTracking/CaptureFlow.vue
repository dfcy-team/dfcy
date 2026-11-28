<template>
  <div>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <div v-show="step === 1">
      <p>先采集当前可见业务区域，再选择办理人。跨域图片可能无法显示，请检查预览并遮挡敏感内容。</p>
      <div class="capture-actions"><el-button :loading="busy" :disabled="screenshotEnabled === false" @click="capture">当前页面截图</el-button><el-button @click="details">提取页面明细</el-button></div>
      <el-alert v-if="screenshotEnabled === false" title="当前菜单未启用截图，可提取页面明细。" type="info" :closable="false" />
      <el-input v-model="description" type="textarea" :rows="8" maxlength="12000" show-word-limit placeholder="可编辑的页面明细或跟踪说明" />
      <ScreenshotEditor v-if="screenshotEnabled !== false" ref="editor" :allow-screen-capture="false" @confirmed="image = $event" />
      <el-button type="primary" :disabled="busy || !canContinue || (!description.trim() && !image)" @click="next">下一步：选择办理人</el-button>
    </div>
    <div v-show="step === 2">
      <el-button :disabled="formRef?.busy || formRef?.hasSavedIssue" @click="step = 1">返回采集内容</el-button>
      <IssueForm v-if="visitedForm" ref="formRef" :context="context" :candidates="candidates" :initial-description="description" :initial-screenshot="image" :hide-capture="true" @created="$emit('created', $event)" />
    </div>
  </div>
</template>
<script setup>
import { ref } from 'vue';
import ScreenshotEditor from './ScreenshotEditor.vue';
import IssueForm from './IssueForm.vue';
import { captureWorkspace, visibleDetails } from './capture';
const props = defineProps({ context: Object, candidates: Object, screenshotEnabled: {type: Boolean, default: true}, canContinue: {type: Boolean, default: false} });
defineEmits(['created']);
const formRef = ref(null), visitedForm = ref(false);
const step = ref(1), description = ref(''), image = ref(null), editor = ref(null), busy = ref(false), error = ref('');
async function capture() {
  busy.value = true; error.value = '';
  try { const blob = await captureWorkspace(); await editor.value.loadImage(blob); }
  catch (e) { error.value = e.message || '截图失败，请重试或提取明细'; }
  finally { busy.value = false; }
}
function details() { error.value = ''; try { description.value = visibleDetails(); } catch (e) { error.value = e.message; } }
function next() {
  if (!props.canContinue) { error.value = '请等待办理人选项加载成功'; return; }
  if (editor.value?.hasUnconfirmed) { error.value = '请先确认截图或移除截图'; return; }
  if (!description.value.trim() && !image.value) return;
  error.value = ''; visitedForm.value = true; step.value = 2;
}
</script>
<style scoped>.capture-actions{display:flex;gap:8px;margin-bottom:12px}.el-textarea{margin:12px 0}.el-button{margin-top:10px}</style>
