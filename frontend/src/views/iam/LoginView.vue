<template>
  <div class="login">
    <section class="brand-side">
      <h1>从一句话需求，到可审计的生产任务</h1>
      <p>生成与审批分离 · 冻结事实不可变 · 执行全程留证</p>
      <div class="tags">
        <el-tag type="info">Maker / Checker 双槽</el-tag>
        <el-tag type="info">Capability 单次授权</el-tag>
        <el-tag type="info">证据链可验证</el-tag>
      </div>
    </section>

    <section class="card">
      <h2>登录</h2>
      <p class="sub">使用企业账号访问，权限随角色生效</p>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="企业邮箱 / 工号" prop="external_subject">
          <el-input v-model="form.external_subject" placeholder="name@company.com" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码" prop="credential">
          <el-input
            v-model="form.credential"
            type="password"
            show-password
            placeholder="请输入密码"
            autocomplete="current-password"
            @keyup.enter="onSubmit"
          />
        </el-form-item>

        <el-alert v-if="errorText" :title="errorText" type="error" :closable="false" show-icon />

        <el-button type="primary" class="submit" :loading="submitting" @click="onSubmit">登录</el-button>
      </el-form>

      <el-divider />
      <el-button disabled class="sso">企业 SSO 登录（暂未开放）</el-button>
      <p class="compliance">登录即表示同意《数据访问与审计条款》</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/request'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const errorText = ref('')

const form = reactive({
  external_subject: '',
  credential: ''
})

const rules: FormRules = {
  external_subject: [
    { required: true, message: '请输入企业邮箱或工号', trigger: 'blur' },
    { min: 3, max: 256, message: '长度需在 3–256 之间', trigger: 'blur' }
  ],
  credential: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 128, message: '密码至少 8 位', trigger: 'blur' }
  ]
}

function mapError(code: string, fallback: string): string {
  switch (code) {
    case 'AUTH_INVALID_CREDENTIALS':
      return '账号或密码不正确'
    case 'AUTH_USER_DISABLED':
      return '账号已停用，请联系项目管理员'
    case 'AUTH_ACCOUNT_LOCKED':
      return '失败次数过多，请 15 分钟后重试'
    case 'AUTH_PROVIDER_DISABLED':
      return '该登录方式未开放'
    default:
      return fallback
  }
}

async function onSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  console.log('[iam] login submit provider=LOCAL')
  submitting.value = true
  errorText.value = ''
  try {
    await auth.login({ provider: 'LOCAL', ...form })
    const redirect = (route.query.redirect as string) || '/overview'
    router.replace(redirect)
  } catch (error) {
    const err = error as ApiError
    console.log('[iam] login fail code=', err.code, 'trace_id=', err.traceId)
    errorText.value = `${mapError(err.code, '登录失败，请稍后重试')}（${err.traceId}）`
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  if (route.query.reason === 'SESSION_EXPIRED') {
    errorText.value = '登录已过期，请重新登录'
  }
})
</script>

<style scoped>
.login {
  display: flex;
  min-height: 100vh;
  background: #f6f7f9;
}
.brand-side {
  width: 620px;
  padding: 96px 80px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.brand-side h1 {
  font-size: 34px;
  line-height: 1.3;
  margin: 0 0 16px;
}
.brand-side p {
  color: #667085;
  line-height: 1.7;
  margin: 0 0 24px;
}
.tags {
  display: flex;
  gap: 8px;
}
.card {
  width: 480px;
  margin: auto 120px auto 0;
  background: #fff;
  border: 1px solid #d9dee7;
  border-radius: 14px;
  padding: 32px;
}
.card h2 {
  margin: 0 0 4px;
  font-size: 22px;
}
.sub {
  color: #667085;
  font-size: 12px;
  margin: 0 0 24px;
}
.submit {
  width: 100%;
  height: 42px;
  margin-top: 8px;
}
.sso {
  width: 100%;
}
.compliance {
  color: #98a2b3;
  font-size: 10px;
  text-align: center;
  margin: 12px 0 0;
}
</style>
