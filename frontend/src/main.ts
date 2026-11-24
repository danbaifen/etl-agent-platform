import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import { capability } from './directives/capability'
import { onUnauthorized } from './api/request'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.directive('capability', capability)

onUnauthorized(() => {
  const auth = useAuthStore()
  auth.reset()
  router.replace({ name: 'Login', query: { reason: 'SESSION_EXPIRED' } })
})

app.mount('#app')
