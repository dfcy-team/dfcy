<script setup>
// 后续对接API路径：GET /api/internal/products/master/
const rows = [
  {
    product_code: 'P-20260707001',
    spu: 'SPU-BAG-001',
    sku: 'SKU-BAG-BLK-S',
    product_name: '便携收纳包',
    category: '户外收纳',
    lifecycle_status: '新品',
    sales_status: '正常',
    archived: '否',
  },
]
</script>

<template>
  <section class="mvp-page">
    <el-card class="mvp-search" shadow="never">
      <el-form inline>
        <el-form-item label="商品编码">
          <el-input placeholder="搜索商品编码" disabled />
        </el-form-item>
        <el-form-item label="销售状态">
          <el-select placeholder="全部状态" disabled>
            <el-option label="正常" value="normal" />
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
          <h2>商品主数据列表</h2>
          <el-button type="primary" disabled>新增商品</el-button>
        </div>
      </template>

      <el-table :data="rows" border>
        <el-table-column prop="product_code" label="商品编码" min-width="150" />
        <el-table-column prop="spu" label="SPU" min-width="140" />
        <el-table-column prop="sku" label="SKU" min-width="150" />
        <el-table-column prop="product_name" label="商品名称" min-width="160" />
        <el-table-column prop="category" label="类目" min-width="120" />
        <el-table-column prop="lifecycle_status" label="生命周期状态" min-width="130" />
        <el-table-column prop="sales_status" label="销售状态" min-width="110" />
        <el-table-column prop="archived" label="是否归档" min-width="100" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
