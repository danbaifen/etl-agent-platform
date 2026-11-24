<template>
  <div>
    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>项目成员</span>
          <el-button v-capability="'iam:member:write'" type="primary" size="small" @click="inviteVisible = true">
            邀请成员
          </el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="members" style="width: 100%">
        <el-table-column prop="display_name" label="姓名" width="140" />
        <el-table-column label="账号（脱敏）" width="220">
          <template #default="{ row }">{{ row.email_masked ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="角色" width="220">
          <template #default="{ row }">
            <el-tag v-for="role in row.roles" :key="role.code" size="small" class="role-tag">
              {{ role.name }}
            </el-tag>
            <span v-if="!row.roles.length" class="muted">无角色</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'" size="small">
              {{ row.status === 'ACTIVE' ? '在职' : '已移除' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近活跃" width="180">
          <template #default="{ row }">{{ formatTime(row.last_login_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button
              v-capability="'iam:role:assign'"
              link
              type="primary"
              @click="openAssign(row)"
            >
              分配角色
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无成员，先邀请一位同事" />
        </template>
      </el-table>
    </el-card>

    <InviteMemberDrawer
      v-model="inviteVisible"
      :project-id="projectId"
      :roles="roles"
      @invited="loadMembers()"
    />

    <AssignRoleDialog
      v-model="assignVisible"
      :project-id="projectId"
      :member="assignTarget"
      :roles="roles"
      @changed="onRoleChanged"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listMembers, listRoles } from '@/api/iam'
import { ApiError } from '@/api/request'
import { useAuthStore } from '@/stores/auth'
import type { MemberResponse, RoleBrief } from '@/types/iam'
import InviteMemberDrawer from '@/components/iam/InviteMemberDrawer.vue'
import AssignRoleDialog from '@/components/iam/AssignRoleDialog.vue'

const auth = useAuthStore()
const members = ref<MemberResponse[]>([])
const roles = ref<RoleBrief[]>([])
const loading = ref(false)
const inviteVisible = ref(false)
const assignVisible = ref(false)
const assignTarget = ref<MemberResponse | null>(null)

const projectId = computed(() => auth.currentProject?.id ?? '')

function formatTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date)
}

async function loadMembers(cursor?: string) {
  if (!projectId.value) return
  loading.value = true
  console.log('[iam] members load cursor=', cursor ?? 'first')
  try {
    const page = await listMembers(projectId.value, { cursor, limit: 20 })
    members.value = cursor ? [...members.value, ...page.items] : page.items
    console.log('[iam] members load ok count=', page.items.length)
  } catch (error) {
    const err = error as ApiError
    console.log('[iam] members load fail code=', err.code)
    ElMessage.error(`${err.message}（${err.traceId}）`)
  } finally {
    loading.value = false
  }
}

async function loadRoles() {
  if (!projectId.value) return
  try {
    roles.value = await listRoles(projectId.value)
  } catch {
    roles.value = []
  }
}

function openAssign(row: MemberResponse) {
  assignTarget.value = row
  assignVisible.value = true
}

function onRoleChanged(member: MemberResponse) {
  const index = members.value.findIndex((m) => m.id === member.id)
  if (index >= 0) members.value[index] = member
}

onMounted(async () => {
  await loadRoles()
  await loadMembers()
})
</script>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.role-tag {
  margin-right: 6px;
}
.muted {
  color: #98a2b3;
  font-size: 12px;
}
</style>
