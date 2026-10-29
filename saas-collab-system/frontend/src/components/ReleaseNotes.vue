<template>
  <el-button text @click="visible = true">更新记录</el-button>
  <el-dialog
    v-model="visible"
    title="更新记录"
    width="min(640px, calc(100vw - 32px))"
    append-to-body
    destroy-on-close
  >
    <div class="release-notes" tabindex="0" aria-label="版本更新列表">
      <article v-for="release in releases" :key="release.version" class="release-note">
        <header class="release-note__heading">
          <h3>V{{ release.version }}</h3>
          <time :datetime="release.date">{{ release.date }}</time>
        </header>
        <ul>
          <li v-for="item in release.changes" :key="item">{{ item }}</li>
        </ul>
      </article>
      <p v-if="!releases.length">暂无更新记录。</p>
    </div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue';
import releaseNotes from '../data/releaseNotes.json';

const visible = ref(false);
const releases = [...releaseNotes].sort((a, b) =>
  b.date.localeCompare(a.date) || b.version.localeCompare(a.version, undefined, { numeric: true })
);
</script>

<style scoped>
.release-notes { max-height: 60vh; overflow-y: auto; overflow-wrap: anywhere; padding-right: 8px; }
.release-note + .release-note { margin-top: 20px; padding-top: 20px; border-top: 1px solid #e2e8f0; }
.release-note__heading { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px 16px; }
.release-note__heading h3 { margin: 0; color: #172033; font-size: 16px; }
.release-note__heading time { color: #64748b; font-size: 13px; }
.release-note ul { margin: 12px 0 0; padding-left: 20px; line-height: 1.8; }
.release-note li + li { margin-top: 4px; }
</style>
