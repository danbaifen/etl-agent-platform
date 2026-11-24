import type { Directive } from 'vue'
import { useAuthStore } from '@/stores/auth'

/** 仅用于渲染层隐藏入口，不作为授权依据。 */
export const capability: Directive<HTMLElement, string> = {
  mounted(el, binding) {
    const auth = useAuthStore()
    if (!auth.has(binding.value)) {
      el.parentNode?.removeChild(el)
    }
  }
}
