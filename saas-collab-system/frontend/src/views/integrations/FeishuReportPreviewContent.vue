<template>
  <article class="report-preview">
    <h3>{{ data.title || '报表预览' }}</h3>
    <p v-if="!card && data.summary">{{ data.summary }}</p>
    <p v-if="data.generated_at" class="preview-muted">生成时间：{{ data.generated_at }}</p>
    <ul v-if="!card && Array.isArray(data.sections) && data.sections.length"><li v-for="(section, index) in data.sections" :key="index">{{ typeof section === 'string' ? section : (section.text || section.title || JSON.stringify(section)) }}</li></ul>
    <section v-if="card" class="card-preview" aria-label="JSON2 卡片本地示意">
      <FeishuCardElement v-for="(element, index) in card.elements" :key="index" :element="element" />
    </section>
  </article>
</template>

<script setup>
import FeishuCardElement from './FeishuCardElement.vue';

defineProps({
  data: { type: Object, required: true },
  card: { type: Object, default: null }
});
</script>

<style scoped>
.report-preview { margin-top: 18px; color: #263246; }
.report-preview h3 { margin: 16px 0 8px; }
.preview-muted { color: #64748b; font-size: 12px; }
.card-preview { margin-top: 16px; padding: 16px; border: 1px solid #d9e1ec; border-radius: 10px; background: #f8fafc; }
.card-preview > * + * { display: block; margin-top: 12px; }
</style>
