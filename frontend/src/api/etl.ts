import { request } from './request'

export interface EnvelopePage<T> {
  items: T[]
  next_cursor?: string | null
}

export const etlApi = {
  // 连接与 Secret
  listConnections: () => request<Record<string, any>[]>({ url: '/connections', method: 'GET' }),
  createConnection: (payload: Record<string, any>) =>
    request<Record<string, any>>({ url: '/connections', method: 'POST', data: payload, idempotent: true }),
  testConnection: (id: string) =>
    request<Record<string, any>>({ url: `/connections/${id}/test`, method: 'POST' }),
  listSecrets: () => request<Record<string, any>[]>({ url: '/secrets', method: 'GET' }),
  createSecret: (payload: Record<string, any>) =>
    request<Record<string, any>>({ url: '/secrets', method: 'POST', data: payload, idempotent: true }),

  // 元数据
  probe: (connectionId: string) =>
    request<Record<string, any>>({
      url: `/connections/${connectionId}/probe`,
      method: 'POST',
      data: { sample: true },
      idempotent: true
    }),
  latestProfile: (connectionId: string) =>
    request<Record<string, any> | null>({ url: `/connections/${connectionId}/profile`, method: 'GET' }),

  // Studio
  listSessions: () => request<Record<string, any>[]>({ url: '/studio/sessions', method: 'GET' }),
  createSession: (payload: Record<string, any>) =>
    request<Record<string, any>>({ url: '/studio/sessions', method: 'POST', data: payload, idempotent: true }),
  getSession: (id: string) =>
    request<Record<string, any>>({ url: `/studio/sessions/${id}`, method: 'GET' }),
  answerInterrupt: (id: string, payload: Record<string, any>) =>
    request<Record<string, any>>({ url: `/studio/interrupts/${id}/answer`, method: 'POST', data: payload }),

  // 版本与门禁
  freeze: (candidateId: string) =>
    request<Record<string, any>>({
      url: `/candidates/${candidateId}/freeze`,
      method: 'POST',
      idempotent: true
    }),
  listPipelines: () => request<Record<string, any>[]>({ url: '/pipelines', method: 'GET' }),
  getVersion: (id: string) => request<Record<string, any>>({ url: `/versions/${id}`, method: 'GET' }),
  diffVersions: (left: string, right: string) =>
    request<Record<string, any>>({ url: `/versions/${left}/diff/${right}`, method: 'GET' }),

  // Harness
  prepare: (versionId: string) =>
    request<Record<string, any>>({
      url: `/versions/${versionId}/prepare`,
      method: 'POST',
      idempotent: true
    }),
  listPreparations: (status?: string) =>
    request<Record<string, any>[]>({
      url: '/preparations',
      method: 'GET',
      params: status ? { status } : undefined
    }),
  getPreparation: (id: string) =>
    request<Record<string, any>>({ url: `/preparations/${id}`, method: 'GET' }),
  approve: (id: string, slotCode: string, decision: string, comment: string) =>
    request<Record<string, any>>({
      url: `/preparations/${id}/approve`,
      method: 'POST',
      data: { slot_code: slotCode, decision, comment }
    }),
  commit: (id: string) =>
    request<Record<string, any>>({ url: `/preparations/${id}/commit`, method: 'POST', idempotent: true }),
  evidence: () => request<Record<string, any>>({ url: '/evidence', method: 'GET' }),

  // 执行
  listRuns: () => request<Record<string, any>[]>({ url: '/runs', method: 'GET' }),
  getRun: (id: string) => request<Record<string, any>>({ url: `/runs/${id}`, method: 'GET' }),
  startRun: (id: string) => request<Record<string, any>>({ url: `/runs/${id}/start`, method: 'POST' }),
  rollbackRun: (id: string, reason: string) =>
    request<Record<string, any>>({ url: `/runs/${id}/rollback`, method: 'POST', data: { reason } }),

  // 评测
  listSuites: () => request<Record<string, any>[]>({ url: '/bench/suites', method: 'GET' }),
  runSuite: (id: string) =>
    request<Record<string, any>>({ url: `/bench/suites/${id}/runs`, method: 'POST' }),
  benchRuns: () => request<Record<string, any>[]>({ url: '/bench/runs', method: 'GET' }),
  benchRun: (id: string) => request<Record<string, any>>({ url: `/bench/runs/${id}`, method: 'GET' })
}
