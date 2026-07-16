import { createApp } from 'vue';
import 'element-plus/theme-chalk/base.css';
import 'element-plus/theme-chalk/el-loading.css';
import 'element-plus/theme-chalk/el-message.css';
import 'element-plus/theme-chalk/el-message-box.css';
import App from './App.vue';
import router from './router';
import { pinia } from './stores';
import { useAuthStore } from './stores/auth';
import { onAuthenticationExpired } from './api/request';
import './styles.css';

const app = createApp(App);
app.use(pinia).use(router);

onAuthenticationExpired(() => {
  const auth = useAuthStore(pinia);
  auth.clearAuthentication('登录状态已过期，请重新登录。');
  if (router.currentRoute.value.path !== '/login') {
    router.replace({ path: '/login', query: { reason: 'expired' } });
  }
});

app.mount('#app');
