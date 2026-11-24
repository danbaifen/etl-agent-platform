<template>
  <div class="page">
    <div class="bar">
      <div v-if="chain">
        <el-tag size="small" :type="chain.intact ? 'success' : 'danger'">
          {{ chain.intact ? '链完整' : '链异常' }}
        </el-tag>
        <span class="mono" style="margin-left: 10px">共 {{ chain.length }} 条记录 · chain {{ chain.chain_id }}</span>
      </div>
      <el-button size="small" @click="load">重新校验</el-button>
    </div>

    <el-alert v-if="chain && !chain.intact" type="error" :closable="false" show-icon
      :title="`校验发现 ${chain.problems.length} 处问题`" style="margin-bottom: 10px">
      <div v-for="(p, i) in chain.problems" :key="i" class="mono">#{{ p.sequence_no }} {{ p.issue }}</div>
    </el-alert>

    <el-table :data="chain?.records ?? []" size="small" border v-loading="loading">
      <el-table-column prop="sequence_no" label="#" width="60" />
      <el-table-column prop="event_type" label="事件" width="200" />
      <el-table-column prop="actor" label="主体" width="150">
        <template #default="{ row }"><span class="mono">{{ String(row.actor).slice(0, 8) }}…</span></template>
      </el-table-column>
      <el-table-column label="制品哈希" min-width="180">
        <template #default="{ row }"><span class="mono">{{ String(row.artifact_sha256).slice(0, 20) }}…</span></template>
      </el-table-column>
      <el-table-column label="前序哈希" min-width="140">
        <template #default="{ row }">
          <span class="mono">{{ row.prev_hash ? String(row.prev_hash).slice(0, 12) + '…' : '（创世）' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="记录哈希" min-width="150">
        <template #default="{ row }"><span class="mono">{{ String(row.record_hash).slice(0, 14) }}…</span></template>
      </el-table-column>
      <el-table-column label="签名" width="150">
        <template #default="{ row }"><span class="mono">{{ row.signature }}</span></template>
      </el-table-column>
      <el-table-column label="时间" width="180">
        <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { etlApi } from '@/api/etl'

const chain = ref<Record<string, any> | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    chain.value = await etlApi.evidence()
  } catch (e: any) {
    ElMessage.error(e.message ?? '校验失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page { padding: 4px; }
.bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.mono { font-family: Consolas, Monaco, monospace; font-size: 12px; }
</style>
