<script setup>
// 后续对接API路径：GET /api/internal/audit/operation-logs/
// 当前页面仅展示Mock数据，不实现真实日志查询。
const rows = [
  {
    operator: 'demo_admin',
    module: '商品主数据',
    action: '查看',
    object_type: 'product',
    object_id: 'P-20260707001',
    ip: '127.0.0.1',
    operated_at: '2026-07-07 10:00',
  },
  {
    operator: 'buyer_mock',
    module: '采购订单',
    action: '创建占位',
    object_type: 'purchase_order',
    object_id: 'PO-20260707001',
    ip: '127.0.0.1',
    operated_at: '2026-07-07 10:10',
  },
]
</script>

<template>
  <section class="mvp-page">
    <el-card class="mvp-search" shadow="never">
      <el-form inline>
        <el-form-item label="操作人">
          <el-input placeholder="搜索操作人" disabled />
        </el-form-item>
        <el-form-item label="模块">
          <el-input placeholder="搜索模块" disabled />
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
          <h2>操作日志列表</h2>
          <el-button type="primary" disabled>导出日志</el-button>
        </div>
      </template>

      <el-table :data="rows" border>
        <el-table-column prop="operator" label="操作人" min-width="120" />
        <el-table-column prop="module" label="模块" min-width="130" />
        <el-table-column prop="action" label="动作" min-width="120" />
        <el-table-column prop="object_type" label="对象类型" min-width="140" />
        <el-table-column prop="object_id" label="对象ID" min-width="160" />
        <el-table-column prop="ip" label="IP" min-width="120" />
        <el-table-column prop="operated_at" label="时间" min-width="160" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
