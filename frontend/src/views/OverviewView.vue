<template>
  <div class="page">
    <el-row :gutter="12">
      <el-col :span="6">
        <div class="card">
          <span class="label">数据源连接</span>
          <b class="value">{{ stats.connections }}</b>
          <span class="hint">其中 {{ stats.prod }} 个生产环境连接</span>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="card">
          <span class="label">Pipeline 版本</span>
          <b class="value">{{ stats.versions }}</b>
          <span class="hint">{{ stats.pipelines }} 条流水线，版本冻结后不可覆盖</span>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="card">
          <span class="label">待审批准备单</span>
          <b class="value">{{ stats.pending }}</b>
          <span class="hint">四眼原则：申请人不可自批</span>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="card">
          <span class="label">执行成功率</span>
          <b class="value">{{ stats.successRate }}</b>
          <span class="hint">共 {{ stats.runs }} 次执行</span>
        </div>
      </el-col>
    </el-row>

    <el-card shadow="never" style="margin-top: 12px">
      <template #header><b>最近执行</b></template>
      <el-table :data="runs.slice(0, 6)" size="small" border>
        <el-table-column prop="task_id" label="任务" width="180">
          <template #default="{ row }"><span class="mono">{{ row.task_id }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'SUCCEEDED' ? 'success' : row.status === 'ABORTED' ? 'danger' : 'info'">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="read_rows" label="读取行" width="100" />
        <el-table-column prop="written_rows" label="写入行" width="100" />
        <el-table-column prop="reject_rows" label="分流" width="90" />
        <el-table-column label="开始时间" min-width="180">
          <template #default="{ row }">{{ row.started_at ? new Date(row.started_at).toLocaleString() : '—' }}</template>
        </el-table-column>
      </el-table>
      <div v-if="!runs.length" class="muted" style="margin-top: 8px">还没有执行记录：先到「Pipeline Studio」生成并冻结一个版本。</div>
    </el-card>

    <el-card shadow="never" style="margin-top: 12px">
      <template #header><b>快捷导航</b></template>
      <div class="quick">
        <el-button @click="go('/connections')">登记数据源并探查元数据</el-button>
        <el-button @click="go('/studio')">用自然语言生成 Pipeline</el-button>
        <el-button @click="go('/runs')">审批准备单 / 监控执行</el-button>
        <el-button @click="go('/governance')">运行 Benchmark 评测</el-button>
        <el-button @click="go('/evidence')">校验证据链</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { etlApi } from '@/api/etl'

const router = useRouter()
const runs = ref<Record<string, any>[]>([])
const stats = reactive({
  connections: 0,
  prod: 0,
  versions: 0,
  pipelines: 0,
  pending: 0,
  runs: 0,
  successRate: '—'
})

const go = (path: string) => router.push(path)

async function load() {
  const [connections, pipelines, preparations, runList] = await Promise.all([
    etlApi.listConnections().catch(() => []),
    etlApi.listPipelines().catch(() => []),
    etlApi.listPreparations('PENDING_APPROVAL').catch(() => []),
    etlApi.listRuns().catch(() => [])
  ])
  stats.connections = connections.length
  stats.prod = connections.filter((c: any) => c.environment === 'PROD').length
  stats.pipelines = pipelines.length
  stats.versions = pipelines.reduce((sum: number, p: any) => sum + (p.version_count ?? 0), 0)
  stats.pending = preparations.length
  runs.value = runList
  stats.runs = runList.length
  const finished = runList.filter((r: any) => ['SUCCEEDED', 'ABORTED', 'FAILED'].includes(r.status))
  stats.successRate = finished.length
    ? `${((finished.filter((r: any) => r.status === 'SUCCEEDED').length / finished.length) * 100).toFixed(0)}%`
    : '—'
}

onMounted(load)
</script>

<style scoped>
.page { padding: 4px; }
.card { background: #fff; border: 1px solid #e5e8ee; border-radius: 8px; padding: 14px 16px; display: flex; flex-direction: column; gap: 6px; }
.label { font-size: 12px; color: #6b7280; }
.value { font-size: 26px; font-weight: 600; }
.hint { font-size: 12px; color: #9aa3af; }
.muted { color: #9aa3af; font-size: 12px; }
.mono { font-family: Consolas, Monaco, monospace; font-size: 12px; }
.quick { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
