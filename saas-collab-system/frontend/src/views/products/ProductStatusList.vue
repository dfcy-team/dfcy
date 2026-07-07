<script setup>
// 后续对接API路径：GET /api/internal/products/status/
const statuses = [
  { status: '新品', description: '新建或首批上架商品', count: 12 },
  { status: '正常', description: '可正常销售商品', count: 86 },
  { status: '爆品', description: '高销量重点商品', count: 9 },
  { status: '滞销', description: '销量低于预期商品', count: 7 },
  { status: '清仓中', description: '正在清理库存商品', count: 5 },
  { status: '已清仓', description: '库存已清完商品', count: 3 },
  { status: '已下架', description: '已停止销售商品', count: 4 },
]
</script>

<template>
  <section class="mvp-page">
    <el-card class="mvp-search" shadow="never">
      <el-form inline>
        <el-form-item label="状态">
          <el-select placeholder="全部状态" disabled>
            <el-option
              v-for="item in statuses"
              :key="item.status"
              :label="item.status"
              :value="item.status"
            />
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
          <h2>商品销售状态</h2>
          <el-button type="primary" disabled>状态配置</el-button>
        </div>
      </template>

      <el-table :data="statuses" border>
        <el-table-column prop="status" label="状态" min-width="120" />
        <el-table-column prop="description" label="说明" min-width="220" />
        <el-table-column prop="count" label="Mock商品数" min-width="120" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看商品</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
