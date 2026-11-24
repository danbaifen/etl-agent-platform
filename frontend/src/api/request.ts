import axios, { type AxiosRequestConfig } from 'axios'
import type { ApiResult } from '@/types/iam'

export class ApiError extends Error {
  code: string
  traceId: string
  retriable: boolean

  constructor(code: string, message: string, traceId: string, retriable = false) {
    super(message)
    this.code = code
    this.traceId = traceId
    this.retriable = retriable
  }
}

function newTraceId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `t-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

const http = axios.create({
  baseURL: '/api/v1',
  withCredentials: true,
  timeout: 20000
})

http.interceptors.request.use((config) => {
  config.headers = config.headers ?? {}
  config.headers['X-Trace-Id'] = newTraceId()
  return config
})

type UnauthorizedHandler = () => void
let unauthorizedHandler: UnauthorizedHandler | null = null

export function onUnauthorized(handler: UnauthorizedHandler) {
  unauthorizedHandler = handler
}

export async function request<T>(config: AxiosRequestConfig & { idempotent?: boolean }): Promise<T> {
  const headers: Record<string, string> = { ...(config.headers as Record<string, string>) }
  if (config.idempotent) {
    headers['Idempotency-Key'] = crypto.randomUUID()
  }

  try {
    const response = await http.request<ApiResult<T>>({ ...config, headers })
    const body = response.data
    if (body.code === 'OK') return body.data
    throw new ApiError(body.code, body.message, body.trace_id, body.retriable ?? false)
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const body = error.response?.data as ApiResult<unknown> | undefined
      if (body?.code) {
        if (error.response?.status === 401) unauthorizedHandler?.()
        throw new ApiError(body.code, body.message, body.trace_id, body.retriable ?? false)
      }
      throw new ApiError('SYS_NETWORK_ERROR', '网络异常，请稍后重试', newTraceId(), true)
    }
    throw error
  }
}
