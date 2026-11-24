import type { Router } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

export function installGuards(router: Router) {
  router.beforeEach(async (to) => {
    const auth = useAuthStore()

    if (to.meta.public) {
      if (auth.isAuthenticated && to.name === 'Login') return { name: 'Overview' }
      return true
    }

    if (!auth.isAuthenticated) {
      try {
        await auth.fetchSession()
      } catch {
        return { name: 'Login', query: { redirect: to.fullPath } }
      }
    }

    const capability = to.meta.capability as string | undefined
    if (capability && !auth.has(capability)) {
      console.warn('[iam] route denied cap=', capability)
      return { name: 'Forbidden' }
    }

    return true
  })
}
