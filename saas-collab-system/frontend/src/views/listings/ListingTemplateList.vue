<script setup>
// 后续对接API路径：GET /api/internal/listings/templates/
const rows = [
  {
    template_name: 'Amazon US 户外收纳模板',
    platform: 'Amazon',
    country: 'US',
    category: 'Sports & Outdoors',
    status: '启用',
  },
]
</script>

<template>
  <section class="mvp-page">
    <el-card class="mvp-search" shadow="never">
      <el-form inline>
        <el-form-item label="模板名称">
          <el-input placeholder="搜索模板名称" disabled />
        </el-form-item>
        <el-form-item label="平台">
          <el-select placeholder="全部平台" disabled>
            <el-option label="Amazon" value="Amazon" />
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
          <h2>刊登模板列表</h2>
          <el-button type="primary" disabled>新增模板</el-button>
        </div>
      </template>

      <el-table :data="rows" border>
        <el-table-column prop="template_name" label="模板名称" min-width="220" />
        <el-table-column prop="platform" label="平台" min-width="100" />
        <el-table-column prop="country" label="国家" min-width="90" />
        <el-table-column prop="category" label="类目" min-width="160" />
        <el-table-column prop="status" label="状态" min-width="100" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
