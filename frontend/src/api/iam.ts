import { request } from './request'
import type {
  AssignRoleRequest,
  InviteMemberRequest,
  LoginRequest,
  LoginResponse,
  MemberPage,
  MemberResponse,
  ProjectResponse,
  RoleBrief,
  SessionResponse
} from '@/types/iam'

export function login(payload: LoginRequest) {
  return request<LoginResponse>({ url: '/auth/login', method: 'POST', data: payload })
}

export function logout() {
  return request<void>({ url: '/auth/logout', method: 'POST' })
}

export function getSession() {
  return request<SessionResponse>({ url: '/auth/session', method: 'GET' })
}

export function switchProject(projectId: string) {
  return request<SessionResponse>({
    url: '/auth/session/project',
    method: 'POST',
    data: { project_id: projectId }
  })
}

export function listProjects(params?: { cursor?: string; limit?: number }) {
  return request<{ items: ProjectResponse[]; next_cursor: string | null }>({
    url: '/projects',
    method: 'GET',
    params
  })
}

export function listMembers(projectId: string, params?: { cursor?: string; limit?: number }) {
  return request<MemberPage>({
    url: `/projects/${projectId}/members`,
    method: 'GET',
    params
  })
}

export function inviteMember(projectId: string, payload: InviteMemberRequest) {
  return request<MemberResponse>({
    url: `/projects/${projectId}/members`,
    method: 'POST',
    data: payload,
    idempotent: true
  })
}

export function updateMember(projectId: string, memberId: string, status: 'ACTIVE' | 'REMOVED') {
  return request<MemberResponse>({
    url: `/projects/${projectId}/members/${memberId}`,
    method: 'PATCH',
    data: { status },
    idempotent: true
  })
}

export function assignRole(projectId: string, memberId: string, payload: AssignRoleRequest) {
  return request<MemberResponse>({
    url: `/projects/${projectId}/members/${memberId}/roles`,
    method: 'POST',
    data: payload,
    idempotent: true
  })
}

export function revokeRole(projectId: string, memberId: string, assignmentId: string) {
  return request<MemberResponse>({
    url: `/projects/${projectId}/members/${memberId}/roles/${assignmentId}`,
    method: 'DELETE'
  })
}

export function listRoles(projectId: string) {
  return request<RoleBrief[]>({ url: `/projects/${projectId}/roles`, method: 'GET' })
}
