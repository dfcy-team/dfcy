<template>
  <AppPage :title="isCategory ? '平台类目映射' : '商品属性映射'" eyebrow="刊登映射" subtitle="维护当前租户的映射关系，不调用外部平台 API。" capability="connected">
    <div class="toolbar"><el-button type="primary" @click="openCreate">新增映射</el-button><el-button :loading="loading" @click="load">刷新</el-button></div>
    <el-table :data="rows" v-loading="loading" border>
      <el-table-column prop="platform_name" label="平台" width="140" /><el-table-column prop="country_code" label="国家/地区" width="90" />
      <el-table-column :prop="isCategory ? 'source_category_code' : 'source_attribute_code'" :label="isCategory ? '内部类目' : '内部属性'" />
      <el-table-column :prop="isCategory ? 'target_category_code' : 'target_attribute_code'" :label="isCategory ? '平台类目' : '平台字段'" /><el-table-column prop="status" label="状态" width="110" />
      <el-table-column label="操作" width="150"><template #default="{ row }"><el-button link type="primary" @click="edit(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">停用</el-button></template></el-table-column>
    </el-table>
    <el-dialog v-model="dialog" :title="editing ? '编辑映射' : '新增映射'" width="560px">
      <el-form label-position="top"><el-form-item label="平台 ID" required><el-input-number v-model="form.platform" :min="1" /></el-form-item><el-form-item label="国家/地区代码"><el-input v-model="form.country_code" /></el-form-item>
        <template v-if="isCategory"><el-form-item label="内部类目代码" required><el-input v-model="form.source_category_code" /></el-form-item><el-form-item label="平台类目代码" required><el-input v-model="form.target_category_code" /></el-form-item><el-form-item label="平台类目名称"><el-input v-model="form.target_category_name" /></el-form-item></template>
        <template v-else><el-form-item label="内部属性代码" required><el-input v-model="form.source_attribute_code" /></el-form-item><el-form-item label="平台属性代码" required><el-input v-model="form.target_attribute_code" /></el-form-item><el-form-item label="是否必填"><el-switch v-model="form.is_required" /></el-form-item></template>
      </el-form>
      <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
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
const blank = () => ({ platform: null, country_code: '', source_category_code: '', target_category_code: '', target_category_name: '', source_attribute_code: '', target_attribute_code: '', is_required: false });
const form = reactive(blank());
function collection(data) { return Array.isArray(data) ? data : data?.results || data?.items || []; }
async function load() { loading.value = true; const response = await (isCategory.value ? fetchCategoryMappings() : fetchAttributeMappings()); loading.value = false; rows.value = response.success ? collection(response.data) : []; }
function openCreate() { editing.value = null; Object.assign(form, blank()); dialog.value = true; }
function edit(row) { editing.value = row.id; Object.assign(form, row); dialog.value = true; }
async function save() { saving.value = true; const response = isCategory.value ? (editing.value ? await updateCategoryMapping(editing.value, form) : await createCategoryMapping(form)) : (editing.value ? await updateAttributeMapping(editing.value, form) : await createAttributeMapping(form)); saving.value = false; if (!response.success) return ElMessage.error(response.message || '保存失败'); dialog.value = false; ElMessage.success('映射已保存'); load(); }
async function remove(row) { try { await ElMessageBox.confirm('确定停用此映射吗？历史刊登草稿会保留。', '确认操作'); } catch { return; } const response = isCategory.value ? await deleteCategoryMapping(row.id) : await deleteAttributeMapping(row.id); if (response.success) { ElMessage.success('映射已停用'); load(); } else ElMessage.error(response.message || '操作失败'); }
onMounted(load);
</script>
<style scoped>.toolbar { display: flex; gap: 10px; margin-bottom: 12px; }</style>
