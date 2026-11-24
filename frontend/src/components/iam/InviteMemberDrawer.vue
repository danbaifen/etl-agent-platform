<template>
  <el-drawer :model-value="modelValue" title="邀请成员" size="420px" @update:model-value="emit('update:modelValue', $event)">
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="企业邮箱 / 工号" prop="external_subject">
        <el-input v-model="form.external_subject" placeholder="name@company.com" />
      </el-form-item>
      <el-form-item label="初始角色" prop="role_codes">
        <el-select v-model="form.role_codes" multiple placeholder="选择角色" style="width: 100%">
          <el-option
            v-for="role in selectableRoles"
            :key="role.code"
            :label="role.name"
            :value="role.code"
          />
        </el-select>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="onSubmit">确定</el-button>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { inviteMember } from '@/api/iam'
import { ApiError } from '@/api/request'
import type { RoleBrief } from '@/types/iam'

const props = defineProps<{
  modelValue: boolean
  projectId: string
  roles: RoleBrief[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  invited: []
}>()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const form = reactive({ external_subject: '', role_codes: [] as string[] })

const selectableRoles = computed(() => props.roles.filter((r) => r.code !== 'PROJECT_ADMIN'))

const rules: FormRules = {
  external_subject: [
    { required: true, message: '请输入企业邮箱或工号', trigger: 'blur' },
    { min: 3, max: 256, message: '长度需在 3–256 之间', trigger: 'blur' }
  ],
  role_codes: [{ required: true, message: '至少选择一个角色', trigger: 'change' }]
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      form.external_subject = ''
      form.role_codes = []
    }
  }
)

async function onSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    await inviteMember(props.projectId, { ...form })
    ElMessage.success('邀请成功')
    emit('invited')
    emit('update:modelValue', false)
  } catch (error) {
    const err = error as ApiError
    const message =
      err.code === 'IAM_USER_NOT_FOUND'
        ? '该账号尚未加入平台，请先由管理员创建'
        : err.code === 'IAM_MEMBER_EXISTS'
          ? '该成员已在项目中'
          : `${err.message}（${err.traceId}）`
    ElMessage.error(message)
  } finally {
    submitting.value = false
  }
}
</script>
