export interface UserBrief {
  id: string
  display_name: string
  status: 'ACTIVE' | 'DISABLED'
}

export interface TenantBrief {
  id: string
  code: string
  name: string
}

export interface ProjectBrief {
  id: string
  code: string
  name: string
  status: 'ACTIVE' | 'SUSPENDED' | 'ARCHIVED'
}

export interface RoleBrief {
  code: string
  name: string
  is_business_approval_role: boolean
}

export interface LoginRequest {
  provider: 'LOCAL' | 'OIDC'
  external_subject: string
  credential: string
}

export interface LoginResponse {
  session_token: string
  expires_at: string
  user: UserBrief
  projects: ProjectBrief[]
}

export interface SessionResponse {
  user: UserBrief
  tenant: TenantBrief
  project: ProjectBrief | null
  roles: string[]
  approval_slots: string[]
  capabilities: string[]
}

export interface MemberResponse {
  id: string
  user_id: string
  display_name: string
  email_masked: string | null
  roles: RoleBrief[]
  status: 'ACTIVE' | 'REMOVED'
  last_login_at: string | null
}

export interface InviteMemberRequest {
  external_subject: string
  role_codes: string[]
}

export interface AssignRoleRequest {
  role_code: string
  valid_from: string | null
  reason: string
}

export interface ProjectResponse {
  id: string
  tenant_id: string
  code: string
  name: string
  status: string
  created_at: string
  updated_at: string
}

export interface MemberPage {
  items: MemberResponse[]
  next_cursor: string | null
}

export interface ApiResult<T> {
  code: string
  message: string
  data: T
  trace_id: string
  retriable?: boolean
}
