import { createRouter, createWebHistory } from 'vue-router'
import { installGuards } from './guards'
import AppLayout from '@/layouts/AppLayout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/iam/LoginView.vue'),
      meta: { title: '登录', public: true }
    },
    {
      path: '/',
      component: AppLayout,
      children: [
        {
          path: '',
          redirect: '/overview'
        },
        {
          path: 'overview',
          name: 'Overview',
          component: () => import('@/views/OverviewView.vue'),
          meta: { title: '总览工作台' }
        },
        {
          path: 'connections',
          name: 'Connections',
          component: () => import('@/views/ConnectionsView.vue'),
          meta: { title: '数据源与资产', capability: 'asset:connection:read' }
        },
        {
          path: 'studio',
          name: 'Studio',
          component: () => import('@/views/StudioView.vue'),
          meta: { title: 'Pipeline Studio', capability: 'studio:session:read' }
        },
        {
          path: 'runs',
          name: 'Runs',
          component: () => import('@/views/RunsView.vue'),
          meta: { title: '运行中心与审批', capability: 'exec:run:read' }
        },
        {
          path: 'governance',
          name: 'Governance',
          component: () => import('@/views/GovernanceView.vue'),
          meta: { title: '安全治理与评测', capability: 'bench:suite:read' }
        },
        {
          path: 'evidence',
          name: 'Evidence',
          component: () => import('@/views/EvidenceView.vue'),
          meta: { title: '证据账本', capability: 'evidence:ledger:read' }
        },
        {
          path: 'settings/members',
          name: 'MemberSettings',
          component: () => import('@/views/iam/MemberSettingsView.vue'),
          meta: {
            title: '成员与设置',
            capability: 'iam:member:read',
            breadcrumb: ['设置', '成员与设置']
          }
        },
        {
          path: '403',
          name: 'Forbidden',
          component: () => import('@/views/ForbiddenView.vue'),
          meta: { title: '无访问权限' }
        }
      ]
    },
    { path: '/:pathMatch(.*)*', redirect: '/overview' }
  ]
})

installGuards(router)

export default router
