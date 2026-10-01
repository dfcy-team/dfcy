<script setup>
import { computed, ref } from 'vue';
import { useRoute } from 'vue-router';
import { requestApi } from '../../api/request';
import { safeSsoCallback } from '../../utils/ssoRedirect';

const route = useRoute();
const busy = ref(false);
const error = ref('');
const employeeDelegation = computed(() => route.query.purpose === 'employee_readonly');
const params = computed(() => {
  const { client_id, redirect_uri, state, code_challenge } = route.query;
  if ([client_id, redirect_uri, state, code_challenge].some(value => typeof value !== 'string')) return null;
  if (!safeSsoCallback(redirect_uri) || !/^[A-Za-z0-9._~-]{16,256}$/.test(state) || !/^[A-Za-z0-9_-]{43}$/.test(code_challenge)) return null;
  if (route.query.purpose !== undefined && !employeeDelegation.value) return null;
  if (employeeDelegation.value && route.query.audience !== 'employee-readonly-v1') return null;
  if (!employeeDelegation.value && route.query.audience !== undefined) return null;
  return employeeDelegation.value
    ? { client_id, redirect_uri, state, code_challenge, audience: 'employee-readonly-v1' }
    : { client_id, redirect_uri, state, code_challenge };
});

async function authorize() {
  if (!params.value || busy.value) return;
  busy.value = true;
  error.value = '';
  try {
    const url = employeeDelegation.value
      ? '/api/employee-readonly/v1/authorize/'
      : '/api/internal/integrations/sso/authorize/';
    const result = await requestApi({ method: 'post', url, data: params.value, noMockFallback: true });
    if (!result.success) throw new Error(result.message || '授权失败');
    const callback = safeSsoCallback(params.value.redirect_uri);
    const target = new URL(result.data?.redirect_url || '');
    if (!callback || target.origin !== callback.origin || target.pathname !== callback.pathname || target.username || target.password || target.hash || target.searchParams.getAll('state').length !== 1 || target.searchParams.get('state') !== params.value.state || target.searchParams.getAll('code').length !== 1 || !target.searchParams.get('code') || [...target.searchParams.keys()].some(key => key !== 'code' && key !== 'state')) {
      throw new Error('服务端返回的回调地址不匹配，已停止跳转');
    }
    window.location.assign(target.href);
  } catch (reason) {
    error.value = reason.message || '授权失败，请联系管理员';
    busy.value = false;
  }
}
</script>

<template>
  <main class="sso-page">
    <section class="sso-card">
      <h1>{{ employeeDelegation ? '确认员工只读委托' : '确认共用登录' }}</h1>
      <p v-if="employeeDelegation">确认后，调用系统可在短时有效期内按您本人的原生权限、数据范围及显式字段授权读取已开放的基础数据。不会传送密码、业务登录令牌或授予写入能力；管理员未启用时将拒绝请求。</p>
      <p v-else>您已在本系统登录。确认后，系统将向调用方发放一次性登录授权码，仅用于获取基础身份；不会传送密码、角色或权限，也不会授予业务数据读取权。</p>
      <el-alert v-if="!params" title="登录请求参数无效，请从调用系统重新发起。" type="error" :closable="false" />
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <p v-if="params" class="callback">回调地址：{{ params.redirect_uri }}</p>
      <el-button type="primary" :loading="busy" :disabled="!params" @click="authorize">确认并返回调用系统</el-button>
    </section>
  </main>
</template>

<style scoped>
.sso-page{min-height:100vh;display:grid;place-items:center;background:#f5f7fb;padding:24px}.sso-card{width:min(100%,560px);padding:32px;background:#fff;border-radius:12px;box-shadow:0 12px 32px #18304b14}.sso-card h1{margin:0 0 16px}.sso-card p{line-height:1.7;color:#546176}.sso-card .callback{word-break:break-all;font-size:13px;margin:20px 0}
</style>
