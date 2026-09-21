<script setup>
import { computed, ref } from 'vue';

const activeSection = ref('boundary');

const safeMethods = ['GET', 'HEAD', 'OPTIONS'];
const blockedMethods = ['POST', 'PUT', 'PATCH', 'DELETE'];

const capabilityRows = [
  { capability: '业务数据查询', owner: 'SaaS 协同系统', status: '允许', detail: '按租户、资源、字段和时间范围限定' },
  { capability: '增量同步', owner: '调用方系统', status: '允许', detail: '使用 updated_at、deleted_at、version 和 next_cursor' },
  { capability: '业务内容写入', owner: '调用方系统', status: '禁止', detail: '不开放新增、修改、删除、审批、发布或任务触发' },
  { capability: 'AI 生成内容回写', owner: '知识库项目', status: '禁止', detail: '摘要、标签、分类、评分和提示词都不回写' },
  { capability: '访问审计', owner: 'SaaS 协同系统', status: '系统记录', detail: '只写独立审计日志，不修改被读取的业务对象' }
];

const contractFields = [
  ['resource_type', '资源类型'],
  ['resource_id', '资源稳定唯一标识'],
  ['tenant_id', '租户隔离标识'],
  ['updated_at', '增量同步水位'],
  ['deleted_at', '删除传播标识'],
  ['version', '数据版本'],
  ['content_hash', '内容幂等校验'],
  ['next_cursor', '分页与断点续传']
];

const boundarySummary = computed(() => `${safeMethods.join(' / ')} 只读，${blockedMethods.join(' / ')} 全部拒绝`);
</script>

<template>
  <main class="knowledge-api-page">
    <header class="page-header">
      <div>
        <p class="section-path">系统管理 · API 数据接入</p>
        <h1>内部系统数据接口</h1>
        <p>本系统向知识库及经授权的内部系统提供统一、受控的业务数据读取能力，不接收调用方回写。</p>
      </div>
      <el-tag type="success" effect="plain" size="large">强制只读</el-tag>
    </header>

    <el-alert
      title="调用方不能新增、修改、删除、审批、发布或触发本系统任务；知识库的索引、切片、向量和 AI 生成内容全部留在知识库项目。"
      type="warning"
      :closable="false"
      show-icon
    />

    <section class="status-grid" aria-label="内部系统接口边界状态">
      <article>
        <span>集成方式</span>
        <strong>HTTPS API</strong>
        <small>不直连业务数据库</small>
      </article>
      <article>
        <span>访问身份</span>
        <strong>独立服务身份</strong>
        <small>不共用管理员账号或人员 JWT</small>
      </article>
      <article>
        <span>HTTP 方法</span>
        <strong>{{ safeMethods.join(' · ') }}</strong>
        <small>所有写方法双重拒绝</small>
      </article>
      <article>
        <span>数据边界</span>
        <strong>租户与字段白名单</strong>
        <small>未显式授权的数据默认拒绝</small>
      </article>
    </section>

    <el-tabs v-model="activeSection" class="content-tabs">
      <el-tab-pane label="读写边界" name="boundary">
        <section class="panel">
          <header><div><h2>只读能力矩阵</h2><p>{{ boundarySummary }}</p></div></header>
          <el-table :data="capabilityRows" stripe>
            <el-table-column prop="capability" label="能力" min-width="160" />
            <el-table-column prop="owner" label="责任项目" min-width="150" />
            <el-table-column label="结论" width="110">
              <template #default="scope">
                <el-tag :type="scope.row.status === '禁止' ? 'danger' : 'success'" effect="plain">{{ scope.row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="detail" label="约束" min-width="300" />
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="数据合同" name="contract">
        <section class="panel">
          <header><div><h2>增量同步字段</h2><p>用于知识库幂等更新、断点续传和删除传播，不包含任何回写协议。</p></div></header>
          <dl class="contract-grid">
            <div v-for="field in contractFields" :key="field[0]">
              <dt>{{ field[0] }}</dt>
              <dd>{{ field[1] }}</dd>
            </div>
          </dl>
        </section>
      </el-tab-pane>

      <el-tab-pane label="安全要求" name="security">
        <section class="panel policy-list">
          <h2>必须满足的安全门</h2>
          <ul>
            <li>凭据固定绑定租户、资源白名单、字段白名单和来源 IP/CIDR。</li>
            <li>路由层和权限层同时拒绝 POST、PUT、PATCH 和 DELETE。</li>
            <li>不开放 webhook、回调、消息队列、RPA、导入、任务触发或共享数据库账号。</li>
            <li>审计只记录请求元数据，不保存凭据原文或完整业务响应。</li>
            <li>连续读取不得改变业务对象的 updated_at、版本、状态或归属。</li>
          </ul>
        </section>
      </el-tab-pane>

      <el-tab-pane label="实施状态" name="delivery">
        <section class="panel delivery-panel">
          <h2>增量交付边界</h2>
          <el-steps direction="vertical" :active="1" finish-status="success">
            <el-step title="菜单与权限入口" description="已建立内部管理入口和只读原则说明" />
            <el-step title="服务身份与授权模型" description="待后端实现，不在本次菜单增量中生成凭据" />
            <el-step title="只读 API 与 OpenAPI 合同" description="待资源和字段白名单审定后实施" />
            <el-step title="虚拟机与阿里云验收" description="先虚拟机验证，再使用独立凭据发布阿里云" />
          </el-steps>
        </section>
      </el-tab-pane>
    </el-tabs>
  </main>
</template>

<style scoped>
.knowledge-api-page { display: grid; gap: 20px; padding: 4px 0 28px; color: #172033; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.page-header h1 { margin: 4px 0 8px; font-size: 28px; line-height: 1.25; }
.page-header p { max-width: 760px; margin: 0; color: #5f6b7a; line-height: 1.7; }
.section-path { color: #7a8699 !important; font-size: 13px; }
.status-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.status-grid article { display: grid; gap: 8px; padding: 18px; border: 1px solid #e4e9f0; border-radius: 10px; background: #fff; }
.status-grid span, .status-grid small { color: #6b7788; }
.status-grid strong { font-size: 17px; }
.content-tabs { padding: 0 20px 20px; border: 1px solid #e4e9f0; border-radius: 10px; background: #fff; }
.panel { padding-top: 8px; }
.panel header { display: flex; justify-content: space-between; margin-bottom: 16px; }
.panel h2 { margin: 0 0 6px; font-size: 19px; }
.panel p { margin: 0; color: #6b7788; line-height: 1.6; }
.contract-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0; margin: 0; border: 1px solid #e4e9f0; border-radius: 8px; overflow: hidden; }
.contract-grid div { display: grid; grid-template-columns: 150px 1fr; gap: 16px; padding: 14px 16px; border-bottom: 1px solid #edf0f4; }
.contract-grid div:nth-child(odd) { border-right: 1px solid #edf0f4; }
.contract-grid dt { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: #2457a7; }
.contract-grid dd { margin: 0; color: #4f5b6b; }
.policy-list ul { display: grid; gap: 12px; padding-left: 20px; color: #3f4a5a; line-height: 1.65; }
.delivery-panel { min-height: 320px; }
@media (max-width: 960px) {
  .status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .contract-grid { grid-template-columns: 1fr; }
  .contract-grid div:nth-child(odd) { border-right: 0; }
}
@media (max-width: 640px) {
  .page-header { flex-direction: column; }
  .status-grid { grid-template-columns: 1fr; }
  .content-tabs { padding-inline: 12px; }
  .contract-grid div { grid-template-columns: 1fr; gap: 6px; }
}
</style>
