<template>
  <div class="page">
    <div class="bar">
      <div class="muted">评测以意图描述驱动 PDP 定级，与线上策略共用同一套风险函数，避免两套口径漂移。</div>
      <el-button size="small" @click="load">刷新</el-button>
    </div>

    <el-table :data="suites" size="small" border v-loading="loading">
      <el-table-column prop="name" label="套件" min-width="180" />
      <el-table-column prop="level" label="层级" width="80" />
      <el-table-column prop="case_count" label="用例数" width="90" />
      <el-table-column label="最近一次" min-width="220">
        <template #default="{ row }">
          <template v-if="row.last_run">
            <el-tag size="small" :type="row.last_run.status === 'SUCCEEDED' ? 'success' : 'info'">
              {{ row.last_run.status }}
            </el-tag>
            <span class="mono"> 准确率 {{ (row.last_run.accuracy * 100).toFixed(1) }}% ·
              P0/P1 拦截 {{ (row.last_run.p0_p1_interception_rate * 100).toFixed(1) }}%</span>
          </template>
          <span v-else class="muted">未运行</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-button size="small" type="primary" :disabled="!can('bench:run:trigger')" @click="onRun(row)">
            触发评测
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <template v-if="result">
      <h4>评测结果 · {{ result.total_cases }} 个用例</h4>
      <el-row :gutter="12">
        <el-col :span="6"><div class="kpi"><span>准确率</span><b>{{ (result.accuracy * 100).toFixed(1) }}%</b></div></el-col>
        <el-col :span="6"><div class="kpi"><span>P0/P1 拦截率</span><b>{{ (result.p0_p1_interception_rate * 100).toFixed(1) }}%</b></div></el-col>
        <el-col :span="6"><div class="kpi"><span>通过用例</span><b>{{ result.passed_cases }} / {{ result.total_cases }}</b></div></el-col>
        <el-col :span="6"><div class="kpi"><span>策略版本</span><b>{{ result.policy_version }}</b></div></el-col>
      </el-row>

      <el-table :data="result.results" size="small" border style="margin-top: 12px">
        <el-table-column prop="case_code" label="用例" width="110" />
        <el-table-column prop="title" label="标题" min-width="200" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'PASSED' ? 'success' : 'danger'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="expected_risk" label="期望" width="80" />
        <el-table-column prop="actual_risk" label="实际" width="80" />
        <el-table-column label="命中规则" min-width="220">
          <template #default="{ row }"><span class="mono">{{ row.matched_rules.join(', ') }}</span></template>
        </el-table-column>
      </el-table>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { etlApi } from '@/api/etl'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const can = (cap: string) => auth.session?.capabilities.includes(cap) ?? false

const suites = ref<Record<string, any>[]>([])
const result = ref<Record<string, any> | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    suites.value = await etlApi.listSuites()
  } catch (e: any) {
    ElMessage.error(e.message ?? '加载失败')
  } finally {
    loading.value = false
  }
}

async function onRun(row: Record<string, any>) {
  try {
    result.value = await etlApi.runSuite(row.id)
    ElMessage.success('评测完成')
    await load()
  } catch (e: any) {
    ElMessage.error(e.message ?? '评测失败')
  }
}

onMounted(load)
</script>

<style scoped>
.page { padding: 4px; }
.bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.muted { color: #9aa3af; font-size: 12px; }
.mono { font-family: Consolas, Monaco, monospace; font-size: 12px; }
.kpi { background: #fff; border: 1px solid #e5e8ee; border-radius: 8px; padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; }
.kpi span { font-size: 12px; color: #6b7280; }
.kpi b { font-size: 20px; }
h4 { font-size: 13px; margin: 16px 0 8px; }
</style>
