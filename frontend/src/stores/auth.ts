import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import * as api from '@/api/iam'
import type { LoginRequest, SessionResponse } from '@/types/iam'

export const useAuthStore = defineStore('auth', () => {
  const session = ref<SessionResponse | null>(null)
  const loading = ref(false)

  const isAuthenticated = computed(() => session.value !== null)
  const roles = computed(() => session.value?.roles ?? [])
  const capabilities = computed(() => new Set(session.value?.capabilities ?? []))
  const currentProject = computed(() => session.value?.project ?? null)

  function has(capability: string): boolean {
    return capabilities.value.has(capability)
  }

  async function login(payload: LoginRequest) {
    loading.value = true
    try {
      await api.login(payload)
      session.value = await api.getSession()
      console.log('[iam] login ok user_id=', session.value.user.id)
    } finally {
      loading.value = false
    }
  }

  async function fetchSession() {
    loading.value = true
    try {
      session.value = await api.getSession()
      console.log('[iam] session loaded roles=', session.value.roles.length, 'caps=', session.value.capabilities.length)
    } catch (error) {
      session.value = null
      console.warn('[iam] session restore fail')
      throw error
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    try {
      await api.logout()
    } finally {
      reset()
    }
  }

  async function switchProject(projectId: string) {
    const from = session.value?.project?.id ?? '-'
    session.value = await api.switchProject(projectId)
    console.log('[iam] switch project from=', from, 'to=', projectId)
  }

  function reset() {
    session.value = null
  }

  return {
    session,
    loading,
    isAuthenticated,
    roles,
    capabilities,
    currentProject,
    has,
    login,
    fetchSession,
    logout,
    switchProject,
    reset
  }
})
