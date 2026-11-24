<template>
  <div class="page">
    <el-steps :active="step" simple style="margin-bottom: 14px">
      <el-step title="需求输入" />
      <el-step title="澄清与生成" />
      <el-step title="门禁与冻结" />
      <el-step title="准备单" />
    </el-steps>

    <el-card shadow="never" class="block">
      <template #header><b>① 自然语言需求</b><span class="muted"> · 源端与目标端从已登记连接中选择</span></template>
      <el-form label-width="88px" size="small">
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="源连接">
              <el-select v-model="form.source_connection_id" style="width: 100%" @change="loadObjects">
                <el-option v-for="c in connections" :key="c.id" :label="`${c.name} (${c.environment})`" :value="c.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="目标连接">
              <el-select v-model="form.target_connection_id" style="width: 100%">
                <el-option v-for="c in connections" :key="c.id" :label="`${c.name} (${c.environment})`" :value="c.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="目标对象">
              <el-input v-model="form.target_object" placeholder="ads_customer" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="源对象">
              <el-select v-model="form.source_object" style="width: 100%" allow-create filterable>
                <el-option v-for="name in objects" :key="name" :label="name" :value="name" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="16">
            <el-form-item label="需求描述">
              <el-input v-model="form.requirement" type="textarea" :rows="2"
                placeholder="把业务库订单表按 customer_id 主键同步到宽表，手机号与邮箱要脱敏" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item>
          <el-button type="primary" :loading="running" @click="onCreate">开始生成</el-button>
          <span class="muted" style="margin-left: 12px">缺参数时会中断提问，回答后从 Checkpoint 恢复</span>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="session" shadow="never" class="block">
      <template #header>
        <b>② 会话与澄清</b>
        <el-tag size="small" style="margin-left: 8px">{{ session.flow?.status }}</el-tag>
        <span class="muted"> · 当前节点 {{ session.flow?.current_node }}</span>
      </template>
      <div class="msgs">
        <div v-for="(m, i) in session.messages" :key="i" :class="['msg', m.role === 'USER' ? 'user' : 'assistant']">
          <span class="who">{{ m.role === 'USER' ? '工程师' : 'Agent' }}</span>{{ m.content }}
        </div>
      </div>
      <el-alert v-if="session.interrupt" type="warning" :closable="false" show-icon style="margin-top: 10px">
        <div style="margin-bottom: 8px">{{ session.interrupt.question_text }}</div>
        <el-select v-if="session.interrupt.ui_schema.type === 'enum'" v-model="answerValue" size="small" style="width: 200px">
          <el-option v-for="opt in session.interrupt.ui_schema.options" :key="opt" :label="opt" :value="opt" />
        </el-select>
        <el-input v-else v-model="answerValue" size="small" style="width: 240px" placeholder="填写参数值" />
        <el-button size="small" type="primary" style="margin-left: 8px" @click="onAnswer">提交并继续</el-button>
      </el-alert>
      <div class="muted" style="margin-top: 8px">
        Checkpoint：{{ (session.flow?.checkpoints ?? []).map((c: any) => `${c.no}:${c.node}`).join(' → ') }}
      </div>
    </el-card>

    <el-card v-if="session?.candidate" shadow="never" class="block">
      <template #header>
        <b>③ 候选方案</b>
        <span class="muted"> · artifact {{ String(session.candidate.artifact_sha256).slice(0, 12) }}…</span>
      </template>
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="主键">{{ plan.target.primary_key }}</el-descriptions-item>
        <el-descriptions-item label="写入模式">{{ plan.target.write_mode }}</el-descriptions-item>
        <el-descriptions-item label="映射字段">{{ plan.transform.mappings.length }}</el-descriptions-item>
        <el-descriptions-item label="拒绝率上限">{{ plan.supervision_contract.max_reject_rate }}</el-descriptions-item>
      </el-descriptions>

      <el-table :data="plan.transform.mappings" size="small" border style="margin-top: 10px">
        <el-table-column prop="source" label="源字段" />
        <el-table-column prop="target" label="目标字段" />
        <el-table-column prop="source_type" label="源类型" width="100" />
        <el-table-column prop="target_type" label="目标类型" width="100" />
        <el-table-column label="敏感" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.sensitivity !== 'NONE'" size="small" type="warning">{{ row.sensitivity }}</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="脱敏" width="110">
          <template #default="{ row }">{{ row.mask_policy ?? '—' }}</template>
        </el-table-column>
      </el-table>

      <el-collapse style="margin-top: 10px">
        <el-collapse-item title="SeaTunnel HOCON" name="hocon">
          <pre class="code">{{ session.candidate.payload.hocon }}</pre>
        </el-collapse-item>
        <el-collapse-item title="DAG 与质量契约" name="dag">
          <pre class="code">{{ JSON.stringify({ dag: plan.dag, quality: plan.quality_contract }, null, 2) }}</pre>
        </el-collapse-item>
      </el-collapse>

      <div style="margin-top: 12px">
        <el-button v-if="can('pipe:version:freeze')" type="primary" :loading="freezing" @click="onFreeze">
          执行门禁并冻结版本
        </el-button>
        <span class="muted" style="margin-left: 12px">门禁为确定性校验，阻断项会逐条列出</span>
      </div>
    </el-card>

    <el-card v-if="version" shadow="never" class="block">
      <template #header>
        <b>④ 冻结结果</b>
        <el-tag size="small" type="success" style="margin-left: 8px">{{ version.gate.status }}</el-tag>
      </template>
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="版本">v{{ version.version_no }}</el-descriptions-item>
        <el-descriptions-item label="SHA256"><span class="mono">{{ version.sha256 }}</span></el-descriptions-item>
        <el-descriptions-item label="组件数">{{ Object.keys(version.components).length }}</el-descriptions-item>
      </el-descriptions>
      <el-table v-if="version.gate.findings.length" :data="version.gate.findings" size="small" border style="margin-top: 10px">
        <el-table-column prop="severity" label="级别" width="90" />
        <el-table-column prop="code" label="规则" width="220" />
        <el-table-column prop="message" label="说明" />
      </el-table>
      <div style="margin-top: 12px">
        <el-button v-if="can('harness:prepare')" type="primary" :loading="preparing" @click="onPrepare">
          生成准备单（Prepare）
        </el-button>
      </div>
    </el-card>

    <el-card v-if="preparation" shadow="never" class="block">
      <template #header>
        <b>⑤ 准备单</b>
        <el-tag size="small" :type="prepTagType" style="margin-left: 8px">{{ preparation.risk_level }} · {{ preparation.status }}</el-tag>
      </template>
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="数据分级">{{ preparation.data_classification }}</el-descriptions-item>
        <el-descriptions-item label="输入指纹">
          <span class="mono">{{ String(preparation.input_fingerprint).slice(0, 16) }}…</span>
        </el-descriptions-item>
        <el-descriptions-item label="快照摘要">
          <span class="mono">{{ String(preparation.snapshot_sha256).slice(0, 16) }}…</span>
        </el-descriptions-item>
        <el-descriptions-item label="读取行数上限">{{ preparation.budget?.max_read_rows }}</el-descriptions-item>
        <el-descriptions-item label="写入字节上限">{{ preparation.budget?.max_write_bytes }}</el-descriptions-item>
        <el-descriptions-item label="拒绝率上限">{{ preparation.budget?.max_reject_rate }}</el-descriptions-item>
      </el-descriptions>
      <div class="muted" style="margin-top: 8px">
        回滚方案：{{ (preparation.rollback_plan?.steps ?? []).join('；') }}
      </div>
      <el-table :data="preparation.slots" size="small" border style="margin-top: 10px">
        <el-table-column prop="slot_code" label="审批槽" width="120" />
        <el-table-column prop="assignee_name" label="指定审批人" />
        <el-table-column prop="status" label="状态" width="120" />
      </el-table>
      <el-alert type="info" :closable="false" show-icon style="margin-top: 10px"
        title="下一步到「运行中心」由各槽位审批人独立批准，再由操作员 Commit。" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { etlApi } from '@/api/etl'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const can = (cap: string) => auth.session?.capabilities.includes(cap) ?? false

const connections = ref<Record<string, any>[]>([])
const objects = ref<string[]>([])
const running = ref(false)
const freezing = ref(false)
const preparing = ref(false)
const answerValue = ref('')
const session = ref<Record<string, any> | null>(null)
const version = ref<Record<string, any> | null>(null)
const preparation = ref<Record<string, any> | null>(null)

const form = reactive({
  source_connection_id: '',
  target_connection_id: '',
  source_object: 'crm_customer',
  target_object: 'ads_customer',
  requirement: '把业务库订单表按 customer_id 主键同步到宽表，手机号与邮箱要脱敏'
})

const plan = computed(() => session.value?.candidate?.payload?.plan ?? { target: {}, transform: { mappings: [] }, supervision_contract: {} })
const step = computed(() => {
  if (preparation.value) return 4
  if (version.value) return 3
  if (session.value?.candidate) return 2
  return 1
})
const prepTagType = computed(() => {
  const risk = preparation.value?.risk_level
  return risk === 'P0' ? 'danger' : risk === 'P1' ? 'warning' : 'info'
})

async function loadConnections() {
  connections.value = await etlApi.listConnections()
  if (!form.source_connection_id && connections.value.length) {
    form.source_connection_id = connections.value[0].id
    form.target_connection_id = connections.value[1]?.id ?? connections.value[0].id
    await loadObjects()
  }
}

async function loadObjects() {
  if (!form.source_connection_id) return
  const profile = await etlApi.latestProfile(form.source_connection_id)
  objects.value = (profile?.objects ?? []).map((o: any) => o.name)
  if (objects.value.length && !objects.value.includes(form.source_object)) {
    form.source_object = objects.value[0]
  }
}

async function onCreate() {
  running.value = true
  version.value = null
  preparation.value = null
  try {
    const data = await etlApi.createSession({ ...form })
    session.value = await etlApi.getSession(data.session_id)
    if (data.interrupt) {
      answerValue.value = ''
      ElMessage.info('缺少必要参数，请回答澄清问题')
    } else {
      ElMessage.success('已生成候选方案')
    }
  } catch (e: any) {
    ElMessage.error(e.message ?? '生成失败')
  } finally {
    running.value = false
  }
}

async function onAnswer() {
  if (!session.value?.interrupt) return
  if (!answerValue.value) {
    ElMessage.warning('请填写参数值')
    return
  }
  running.value = true
  try {
    const field = session.value.interrupt.ui_schema.field
    const data = await etlApi.answerInterrupt(session.value.interrupt.id, { [field]: answerValue.value })
    session.value = await etlApi.getSession(data.session_id)
    ElMessage.success(data.candidate ? '已从 Checkpoint 恢复并生成候选' : '继续澄清中')
  } catch (e: any) {
    ElMessage.error(e.message ?? '提交失败')
  } finally {
    running.value = false
  }
}

async function onFreeze() {
  if (!session.value?.candidate) return
  freezing.value = true
  try {
    const data = await etlApi.freeze(session.value.candidate.id)
    version.value = await etlApi.getVersion(data.version_id)
    ElMessage.success(`门禁 ${data.gate.status}，版本 v${data.version_no} 已冻结`)
  } catch (e: any) {
    ElMessage.error(e.message ?? '门禁未通过')
  } finally {
    freezing.value = false
  }
}

async function onPrepare() {
  if (!version.value) return
  preparing.value = true
  try {
    preparation.value = await etlApi.prepare(version.value.id)
    ElMessage.success(`准备单已冻结，风险等级 ${preparation.value?.risk_level}`)
  } catch (e: any) {
    ElMessage.error(e.message ?? '生成准备单失败')
  } finally {
    preparing.value = false
  }
}

onMounted(loadConnections)
</script>

<style scoped>
.page { padding: 4px; }
.block { margin-bottom: 12px; }
.muted { color: #9aa3af; font-size: 12px; }
.msgs { display: flex; flex-direction: column; gap: 6px; }
.msg { font-size: 13px; padding: 6px 10px; border-radius: 6px; max-width: 78%; }
.msg.user { background: #eef2ff; align-self: flex-end; }
.msg.assistant { background: #f5f6f8; align-self: flex-start; }
.who { color: #6b7280; margin-right: 8px; font-size: 12px; }
.code { background: #0f172a; color: #d7e0ea; padding: 12px; border-radius: 6px; font-size: 12px; overflow: auto; }
.mono { font-family: Consolas, Monaco, monospace; font-size: 12px; }
</style>
