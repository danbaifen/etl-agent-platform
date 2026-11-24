<template>
  <div class="page">
    <div class="toolbar">
      <div class="hint">连接配置只保存非敏感信息，口令一律走 Secret 引用；探查为只读，样本经脱敏后才落库。</div>
      <div class="actions">
        <el-button v-if="can('meta:probe:run')" @click="probeFirst" :disabled="!connections.length">
          探查首个连接
        </el-button>
        <el-button v-if="can('asset:connection:write')" type="primary" @click="openCreate">新建连接</el-button>
      </div>
    </div>

    <el-table :data="connections" v-loading="loading" border size="small">
      <el-table-column prop="name" label="连接名称" min-width="160" />
      <el-table-column prop="connection_type" label="类型" width="110" />
      <el-table-column prop="environment" label="环境" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.environment === 'PROD' ? 'danger' : 'info'">{{ row.environment }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="数据库路径" min-width="260">
        <template #default="{ row }">
          <span class="mono">{{ row.safe_config?.database_path || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="最近连通性" min-width="170">
        <template #default="{ row }">
          <template v-if="row.last_test">
            <el-tag size="small" :type="row.last_test.result === 'SUCCESS' ? 'success' : 'danger'">
              {{ row.last_test.result }}
            </el-tag>
            <span class="mono muted"> {{ row.last_test.latency_ms }}ms</span>
          </template>
          <span v-else class="muted">未测试</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="onTest(row)" :loading="busy === row.id">测试</el-button>
          <el-button size="small" @click="onProbe(row)" :disabled="!can('meta:probe:run')">探查</el-button>
          <el-button size="small" type="primary" link @click="onViewProfile(row)">结构</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createVisible" title="新建连接" width="560px">
      <el-form :model="form" label-width="96px">
        <el-form-item label="连接名称"><el-input v-model="form.name" placeholder="CRM 生产库" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.connection_type" style="width: 100%">
            <el-option label="SQLITE（可本地真跑）" value="SQLITE" />
            <el-option label="MySQL" value="MYSQL" disabled />
            <el-option label="Doris" value="DORIS" disabled />
            <el-option label="PostgreSQL" value="POSTGRESQL" disabled />
          </el-select>
        </el-form-item>
        <el-form-item label="环境">
          <el-radio-group v-model="form.environment">
            <el-radio-button value="DEV">DEV</el-radio-button>
            <el-radio-button value="STAGING">STAGING</el-radio-button>
            <el-radio-button value="PROD">PROD</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="数据库路径">
          <el-input v-model="form.database_path" placeholder="D:/data/source.db" />
        </el-form-item>
        <el-alert type="info" :closable="false" show-icon
          title="当前实现仅 SQLITE 支持真实连通性测试与探查，其他类型会明确返回 UNSUPPORTED。" />
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onCreate">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="62%">
      <div v-if="!profile" class="muted">暂无元数据快照，先点「探查」。</div>
      <div v-else>
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="快照版本">v{{ profile.version_no }}</el-descriptions-item>
          <el-descriptions-item label="对象数">{{ profile.object_count }}</el-descriptions-item>
          <el-descriptions-item label="摘要">
            <span class="mono">{{ String(profile.profile_sha256).slice(0, 16) }}…</span>
          </el-descriptions-item>
        </el-descriptions>
        <el-collapse v-model="openObjects" style="margin-top: 12px">
          <el-collapse-item v-for="obj in profile.objects" :key="obj.id" :name="obj.id">
            <template #title>
              <b>{{ obj.name }}</b>
              <span class="muted" style="margin-left: 10px">约 {{ obj.row_estimate }} 行 · {{ obj.columns.length }} 列</span>
            </template>
            <el-table :data="obj.columns" size="small" border>
              <el-table-column prop="name" label="字段" width="140" />
              <el-table-column prop="data_type" label="类型" width="100" />
              <el-table-column label="空值率" width="90">
                <template #default="{ row }">{{ row.null_ratio ?? '-' }}</template>
              </el-table-column>
              <el-table-column prop="distinct_estimate" label="基数" width="80" />
              <el-table-column label="敏感" width="90">
                <template #default="{ row }">
                  <el-tag v-if="row.sensitivity !== 'NONE'" size="small" type="warning">{{ row.sensitivity }}</el-tag>
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column label="脱敏样本" min-width="220">
                <template #default="{ row }">
                  <span class="mono">{{ row.samples?.length ? row.samples.join(' | ') : '—' }}</span>
                </template>
              </el-table-column>
            </el-table>
          </el-collapse-item>
        </el-collapse>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { etlApi } from '@/api/etl'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const can = (cap: string) => auth.session?.capabilities.includes(cap) ?? false

const connections = ref<Record<string, any>[]>([])
const loading = ref(false)
const busy = ref('')
const createVisible = ref(false)
const saving = ref(false)
const drawerVisible = ref(false)
const drawerTitle = ref('')
const profile = ref<Record<string, any> | null>(null)
const openObjects = ref<string[]>([])

const form = reactive({
  name: '本地演示库',
  connection_type: 'SQLITE',
  environment: 'DEV',
  database_path: ''
})

async function load() {
  loading.value = true
  try {
    connections.value = await etlApi.listConnections()
  } catch (e: any) {
    ElMessage.error(e.message ?? '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  createVisible.value = true
}

async function onCreate() {
  if (!form.name || !form.database_path) {
    ElMessage.warning('连接名称与数据库路径必填')
    return
  }
  saving.value = true
  try {
    await etlApi.createConnection({
      name: form.name,
      connection_type: form.connection_type,
      environment: form.environment,
      safe_config: { database_path: form.database_path }
    })
    ElMessage.success('连接已创建')
    createVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message ?? '创建失败')
  } finally {
    saving.value = false
  }
}

async function onTest(row: Record<string, any>) {
  busy.value = row.id
  try {
    const result = await etlApi.testConnection(row.id)
    if (result.result === 'SUCCESS') ElMessage.success(`连通正常 ${result.latency_ms}ms`)
    else ElMessage.error(result.safe_error ?? result.result)
    await load()
  } catch (e: any) {
    ElMessage.error(e.message ?? '测试失败')
  } finally {
    busy.value = ''
  }
}

async function onProbe(row: Record<string, any>) {
  busy.value = row.id
  try {
    const result = await etlApi.probe(row.id)
    ElMessage.success(`探查完成 v${result.version_no}`)
    await onViewProfile(row)
  } catch (e: any) {
    ElMessage.error(e.message ?? '探查失败')
  } finally {
    busy.value = ''
  }
}

async function onViewProfile(row: Record<string, any>) {
  drawerTitle.value = `${row.name} · 元数据与脱敏样本`
  drawerVisible.value = true
  profile.value = await etlApi.latestProfile(row.id)
  openObjects.value = profile.value?.objects?.map((o: any) => o.id) ?? []
}

async function probeFirst() {
  if (connections.value.length) await onProbe(connections.value[0])
}

onMounted(load)
</script>

<style scoped>
.page { padding: 4px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 16px; }
.hint { font-size: 12px; color: #6b7280; }
.actions { display: flex; gap: 8px; }
.mono { font-family: Consolas, Monaco, monospace; font-size: 12px; }
.muted { color: #9aa3af; }
</style>
