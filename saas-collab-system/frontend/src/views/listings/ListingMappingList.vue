<template>
  <AppPage :title="isCategory ? '平台类目映射' : '商品属性映射'" eyebrow="LISTING MAPPINGS" subtitle="维护租户内的本地商品字段与平台字段映射。" capability="connected">
    <div class="toolbar"><el-button type="primary" @click="openCreate">新增映射</el-button><el-button @click="load">刷新</el-button></div>
    <el-table :data="rows" v-loading="loading" border>
      <el-table-column prop="platform_name" label="平台" width="130" />
      <el-table-column :prop="isCategory ? 'source_category_code' : 'source_attribute_code'" :label="isCategory ? '内部类目' : '内部属性'" />
      <el-table-column :prop="isCategory ? 'target_category_code' : 'target_attribute_code'" :label="isCategory ? '平台类目' : '平台属性'" />
      <el-table-column prop="country_code" label="国家" width="90" />
      <el-table-column prop="status" label="状态" width="110" />
      <el-table-column label="操作" width="120"><template #default="{row}"><el-button link type="primary" @click="edit(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">停用</el-button></template></el-table-column>
    </el-table>
    <el-dialog v-model="dialog" :title="editing ? '编辑映射' : '新增映射'" width="520px">
      <el-form label-position="top"><el-form-item label="平台 ID" required><el-input-number v-model="form.platform" :min="1" /></el-form-item><el-form-item label="国家代码"><el-input v-model="form.country_code" /></el-form-item><template v-if="isCategory"><el-form-item label="内部类目编码" required><el-input v-model="form.source_category_code" /></el-form-item><el-form-item label="平台类目编码" required><el-input v-model="form.target_category_code" /></el-form-item><el-form-item label="平台类目名称"><el-input v-model="form.target_category_name" /></el-form-item></template><template v-else><el-form-item label="内部属性编码" required><el-input v-model="form.source_attribute_code" /></el-form-item><el-form-item label="平台属性编码" required><el-input v-model="form.target_attribute_code" /></el-form-item><el-form-item label="必填"><el-switch v-model="form.is_required" /></el-form-item></template></el-form>
      <template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import { createAttributeMapping, createCategoryMapping, deleteAttributeMapping, deleteCategoryMapping, fetchAttributeMappings, fetchCategoryMappings, updateAttributeMapping, updateCategoryMapping } from '../../api/listings';
const props = defineProps({ mode: { type: String, default: 'category' } });
const isCategory = computed(() => props.mode === 'category'); const rows = ref([]); const loading = ref(false); const saving = ref(false); const dialog = ref(false); const editing = ref(null);
const form = reactive({ platform: null, country_code: '', source_category_code: '', target_category_code: '', target_category_name: '', source_attribute_code: '', target_attribute_code: '', is_required: false });
function reset() { Object.assign(form, { platform: null, country_code: '', source_category_code: '', target_category_code: '', target_category_name: '', source_attribute_code: '', target_attribute_code: '', is_required: false }); }
async function load() { loading.value = true; const response = await (isCategory.value ? fetchCategoryMappings() : fetchAttributeMappings()); loading.value = false; rows.value = response.success ? (response.data?.results || response.data || []) : []; }
function openCreate() { editing.value = null; reset(); dialog.value = true; }
function edit(row) { editing.value = row.id; Object.assign(form, row); dialog.value = true; }
async function save() { saving.value = true; const request = isCategory.value ? (editing.value ? updateCategoryMapping(editing.value, form) : createCategoryMapping(form)) : (editing.value ? updateAttributeMapping(editing.value, form) : createAttributeMapping(form)); const response = await request; saving.value = false; if (!response.success) return ElMessage.error(response.message || '保存失败'); dialog.value = false; ElMessage.success('映射已保存'); load(); }
async function remove(row) { try { await ElMessageBox.confirm('停用后不会删除历史草稿，确认继续？', '停用映射'); } catch { return; } const response = await (isCategory.value ? deleteCategoryMapping(row.id) : deleteAttributeMapping(row.id)); if (response.success) load(); else ElMessage.error(response.message || '操作失败'); }
onMounted(load);
</script>

<style scoped>.toolbar { display:flex; gap:10px; margin-bottom:12px; }</style>
