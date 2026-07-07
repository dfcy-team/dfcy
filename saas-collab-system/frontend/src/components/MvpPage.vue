<script setup>
defineProps({
  title: {
    type: String,
    required: true,
  },
  rows: {
    type: Array,
    default: () => [],
  },
})
</script>

<template>
  <section class="mvp-page">
    <el-card class="mvp-search" shadow="never">
      <el-form inline>
        <el-form-item label="关键词">
          <el-input placeholder="搜索条件占位" disabled />
        </el-form-item>
        <el-form-item label="状态">
          <el-select placeholder="全部" disabled>
            <el-option label="全部" value="all" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" disabled>搜索</el-button>
          <el-button disabled>重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="mvp-table-card" shadow="never">
      <template #header>
        <div class="mvp-table-header">
          <h2>{{ title }}</h2>
          <div>
            <el-button type="primary" disabled>新增</el-button>
            <el-button disabled>导出</el-button>
          </div>
        </div>
      </template>

      <el-table :data="rows" border>
        <el-table-column prop="id" label="编号" min-width="140" />
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column prop="status" label="状态" min-width="120" />
        <el-table-column prop="owner" label="负责人" min-width="120" />
        <el-table-column prop="updated_at" label="更新时间" min-width="160" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看</el-button>
            <el-button link type="primary" disabled>编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
