<template>
  <div class="layout">
    <aside class="side">
      <div class="brand">
        <span class="logo">ETL-Agent</span>
        <el-tag size="small" type="info">生产</el-tag>
      </div>
      <nav>
        <router-link
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          active-class="active"
        >
          {{ item.label }}
        </router-link>
      </nav>
      <div class="side-foot">v0.2 · M01–M12</div>
    </aside>

    <div class="main">
      <header class="top">
        <div class="crumb">
          <span class="title">{{ route.meta.title ?? '' }}</span>
          <span v-if="Array.isArray(route.meta.breadcrumb)" class="sub">
            {{ (route.meta.breadcrumb as string[]).join(' / ') }}
          </span>
        </div>
        <div class="right">
          <el-select
            v-if="auth.session?.project"
            :model-value="auth.currentProject?.id"
            size="small"
            style="width: 180px"
            @change="onSwitch"
          >
            <el-option label="当前项目" :value="auth.currentProject?.id ?? ''" disabled />
          </el-select>
          <el-tag size="small">{{ roleLabel }}</el-tag>
          <span class="user">{{ auth.session?.user.display_name }}</span>
          <el-button link @click="onLogout">退出</el-button>
        </div>
      </header>

      <main class="content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const navItems = [
  { to: '/overview', label: '总览工作台' },
  { to: '/connections', label: '数据源与资产' },
  { to: '/studio', label: 'Pipeline Studio' },
  { to: '/runs', label: '运行中心与审批' },
  { to: '/governance', label: '安全治理与评测' },
  { to: '/evidence', label: '证据账本' },
  { to: '/settings/members', label: '成员与设置' }
]

const roleLabel = computed(() => (auth.roles.length ? auth.roles.join(' / ') : '无角色'))

async function onSwitch(projectId: string) {
  if (!projectId) return
  await auth.switchProject(projectId)
  router.go(0)
}

async function onLogout() {
  await auth.logout()
  router.replace({ name: 'Login' })
}
</script>

<style scoped>
.layout {
  display: flex;
  min-height: 100vh;
  background: #f6f7f9;
}
.side {
  width: 232px;
  background: #fff;
  border-right: 1px solid #d9dee7;
  display: flex;
  flex-direction: column;
}
.brand {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 16px;
  border-bottom: 1px solid #edf0f5;
}
.logo {
  font-weight: 700;
}
nav {
  padding: 12px 0;
  flex: 1;
}
.nav-item {
  display: block;
  padding: 10px 16px;
  color: #1d2129;
  text-decoration: none;
  font-size: 13px;
}
.nav-item.active {
  background: #edf1fe;
  color: #2b5ce6;
  font-weight: 600;
}
.side-foot {
  padding: 12px 16px;
  color: #98a2b3;
  font-size: 11px;
}
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.top {
  height: 56px;
  background: #fff;
  border-bottom: 1px solid #d9dee7;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}
.crumb {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.title {
  font-size: 15px;
  font-weight: 600;
}
.sub {
  font-size: 11px;
  color: #98a2b3;
}
.right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.user {
  font-size: 13px;
}
.content {
  padding: 24px 32px;
  flex: 1;
}
</style>
