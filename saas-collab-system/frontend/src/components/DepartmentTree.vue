<template>
  <section class="department-tree" aria-label="组织树">
    <header class="department-tree__header">
      <div>
        <strong>组织树</strong>
        <small>当前租户可见范围</small>
      </div>
      <el-button
        v-if="canManage"
        link
        type="primary"
        @click="$emit('add-root')"
      >新增根部门</el-button>
    </header>
    <el-input
      ref="searchInput"
      v-model="search"
      clearable
      placeholder="搜索部门"
      @input="filterTree"
    />
    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      type="error"
      :closable="false"
      show-icon
      class="department-tree__alert"
    />
    <el-skeleton v-if="loading" :rows="5" animated />
    <el-empty v-else-if="!nodes.length" description="暂无可见部门" :image-size="72" />
    <el-tree
      v-else
      ref="treeRef"
      :data="nodes"
      node-key="id"
      :props="{ label: 'name', children: 'children' }"
      :filter-node-method="filterNode"
      :expand-on-click-node="false"
      default-expand-all
      highlight-current
      :current-node-key="selectedId || undefined"
      @node-click="selectNode"
    >
      <template #default="{ data }">
        <div class="department-tree__node">
          <span class="department-tree__label">
            <span>{{ departmentDisplayName(data.name) }}</span>
            <small v-if="showCounts && data.direct_user_count !== null && data.direct_user_count !== undefined">
              {{ data.direct_user_count }}人<span v-if="data.descendant_user_count">，下级{{ data.descendant_user_count }}人</span>
            </small>
          </span>
          <span v-if="canManage" class="department-tree__actions">
            <el-dropdown trigger="click" @command="(command) => handleAction(command, data)">
              <el-button link type="primary" @click.stop>操作</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="add-child">新增子部门</el-dropdown-item>
                  <el-dropdown-item command="edit">编辑</el-dropdown-item>
                  <el-dropdown-item command="toggle-status">
                    {{ data.status === 'active' ? '停用' : '启用' }}
                  </el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </span>
        </div>
      </template>
    </el-tree>
    <button
      v-if="showAll"
      type="button"
      class="department-tree__all"
      :class="{ 'is-selected': allSelected }"
      @click="$emit('select-all')"
    >
      <span>全部可见用户</span>
      <small>清除部门和未分配筛选</small>
    </button>
    <button
      v-if="showUnassigned"
      type="button"
      class="department-tree__unassigned"
      :class="{ 'is-selected': unassignedSelected }"
      @click="$emit('select-unassigned')"
    >
      <span>未分配人员</span>
      <small>主部门和兼任部门均为空</small>
    </button>
  </section>
</template>

<script setup>
import { ref } from 'vue';
import { departmentDisplayName } from '../utils/adminDisplayLabels';

defineProps({
  nodes: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
  selectedId: { type: [Number, String], default: null },
  canManage: { type: Boolean, default: false },
  showCounts: { type: Boolean, default: true },
  showAll: { type: Boolean, default: false },
  allSelected: { type: Boolean, default: false },
  showUnassigned: { type: Boolean, default: false },
  unassignedSelected: { type: Boolean, default: false },
});

const emit = defineEmits(['select', 'select-all', 'select-unassigned', 'add-root', 'add-child', 'edit', 'toggle-status', 'delete']);

const search = ref('');
const treeRef = ref(null);

function filterNode(value, data) {
  if (!value) return true;
  const query = String(value).toLowerCase();
  const original = String(data.name || '').toLowerCase();
  const display = departmentDisplayName(data.name).toLowerCase();
  return original.includes(query) || display.includes(query);
}

function filterTree() {
  treeRef.value?.filter(search.value);
}

function selectNode(data) {
  // Keep the payload at the node level so both management and directory pages
  // share one visibility and selection contract.
  emit('select', data);
}

function handleAction(command, node) {
  emit(command, node);
}
</script>

<style scoped>
.department-tree { display: grid; gap: 10px; padding: 14px; border: 1px solid #dbe3ec; border-radius: 8px; background: #fff; }
.department-tree__header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.department-tree__header strong, .department-tree__header small { display: block; }
.department-tree__header small { margin-top: 3px; color: #64748b; font-size: 11px; }
.department-tree__alert { margin: 0; }
.department-tree__node { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; min-width: 0; }
.department-tree__label { display: inline-flex; align-items: baseline; gap: 7px; min-width: 0; overflow: hidden; }
.department-tree__label > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.department-tree__label small { color: #64748b; font-size: 11px; white-space: nowrap; }
.department-tree__actions { display: none; flex: 0 0 auto; }
.department-tree__node:hover .department-tree__actions, .el-tree-node:focus-within .department-tree__actions { display: inline-flex; }
.department-tree__all { display: grid; gap: 3px; width: 100%; padding: 9px 12px; border: 1px dashed #93c5fd; border-radius: 6px; background: #f8fbff; color: #1d4ed8; text-align: left; cursor: pointer; }
.department-tree__all small { color: #64748b; font-size: 11px; }
.department-tree__all.is-selected { border-style: solid; background: #eff6ff; }
.department-tree__unassigned { display: grid; gap: 3px; width: 100%; padding: 9px 12px; border: 1px dashed #cbd5e1; border-radius: 6px; background: #fff; color: #334155; text-align: left; cursor: pointer; }
.department-tree__unassigned small { color: #64748b; font-size: 11px; }
.department-tree__unassigned.is-selected { border-color: #409eff; background: #eff6ff; color: #1d4ed8; }
</style>
