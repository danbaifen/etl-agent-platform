<template>
  <el-dialog
    :model-value="modelValue"
    title="分配角色"
    width="480px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="角色" prop="role_code">
        <el-select v-model="form.role_code" placeholder="选择角色" style="width: 100%">
          <el-option
            v-for="role in roles"
            :key="role.code"
            :label="role.name"
            :value="role.code"
            :disabled="heldCodes.includes(role.code)"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="分配理由" prop="reason">
        <el-input v-model="form.reason" type="textarea" :rows="3" maxlength="256" show-word-limit />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="onSubmit">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { assignRole } from '@/api/iam'
import { ApiError } from '@/api/request'
import type { MemberResponse, RoleBrief } from '@/types/iam'

const props = defineProps<{
  modelValue: boolean
  projectId: string
  member: MemberResponse | null
  roles: RoleBrief[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  changed: [member: MemberResponse]
}>()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const form = reactive({ role_code: '', reason: '' })

const heldCodes = computed(() => (props.member?.roles ?? []).map((r) => r.code))

const rules: FormRules = {
  role_code: [{ required: true, message: '请选择角色', trigger: 'change' }],
  reason: [
    { required: true, message: '请填写分配理由（不少于 3 字）', trigger: 'blur' },
    { min: 3, max: 256, message: '理由长度需在 3–256 之间', trigger: 'blur' }
  ]
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      form.role_code = ''
      form.reason = ''
    }
  }
)

async function onSubmit() {
  if (!formRef.value || !props.member) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const updated = await assignRole(props.projectId, props.member.id, {
      role_code: form.role_code,
      valid_from: null,
      reason: form.reason
    })
    ElMessage.success('角色已分配')
    emit('changed', updated)
    emit('update:modelValue', false)
  } catch (error) {
    const err = error as ApiError
    const message =
      err.code === 'IAM_ROLE_ALREADY_ASSIGNED' ? '该成员已持有此角色' : `${err.message}（${err.traceId}）`
    ElMessage.error(message)
  } finally {
    submitting.value = false
  }
}
</script>
