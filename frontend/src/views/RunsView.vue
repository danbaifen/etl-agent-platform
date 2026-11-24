<template>
  <div class="page">
    <el-tabs v-model="tab">
      <el-tab-pane label="准备单与审批" name="prep">
        <el-table :data="preparations" v-loading="loadingPrep" size="small" border>
          <el-table-column label="风险" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.risk_level === 'P0' ? 'danger' : row.risk_level === 'P1' ? 'warning' : 'info'">
                {{ row.risk_level }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="data_classification" label="数据分级" width="110" />
          <el-table-column label="状态" width="140">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'APPROVED' ? 'success' : row.status === 'REJECTED' ? 'danger' : 'info'">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="审批槽" min-width="240">
            <template #default="{ row }">
              <el-tag v-for="s in row.slots" :key="s.id" size="small" style="margin-right: 6px"
                :type="s.status === 'APPROVED' ? 'success' : s.status === 'REJECTED' ? 'danger' : 'info'">
                {{ s.slot_code }} · {{ s.assignee_name }} · {{ s.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="300" fixed="right">
            <template #default="{ row }">
              <el-button size="small" v-if="mySlot(row)" @click="openApprove(row)">审批</el-button>
              <el-button size="small" type="primary" v-if="can('harness:commit') && row.status === 'APPROVED'"
                @click="onCommit(row)">Commit</el-button>
              <el-button size="small" link @click="openPrep(row)">准备单</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="执行监控" name="runs">
        <div class="bar">
          <el-button size="small" @click="loadRuns">刷新</el-button>
          <span class="muted">执行在本地进程内同步完成，指标为真实读写统计</span>
        </div>
        <el-table :data="runs" v-loading="loadingRuns" size="small" border>
          <el-table-column prop="task_id" label="任务" width="170">
            <template #default="{ row }"><span class="mono">{{ row.task_id }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row.status)">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="read_rows" label="读取行数" width="100" />
          <el-table-column prop="written_rows" label="写入行数" width="100" />
          <el-table-column prop="reject_rows" label="分流行数" width="100" />
          <el-table-column prop="throughput" label="吞吐(行/s)" width="110" />
          <el-table-column label="制品摘要" min-width="150">
            <template #default="{ row }"><span class="mono">{{ String(row.artifact_sha256).slice(0, 12) }}…</span></template>
          </el-table-column>
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }">
              <el-button size="small" v-if="can('exec:run:control') && row.status === 'PENDING'" @click="onStart(row)">
                启动执行
              </el-button>
              <el-button size="small" link @click="openRun(row)">详情</el-button>
              <el-button size="small" type="danger" link
                v-if="can('exec:run:control') && ['ABORTED','FAILED','SUCCEEDED'].includes(row.status)"
                @click="onRollback(row)">受管回滚</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="approveVisible" title="独立审批" width="520px">
      <el-alert v-if="approveTarget" type="info" :closable="false" show-icon style="margin-bottom: 10px"
        :title="`风险 ${approveTarget.risk_level}｜数据分级 ${approveTarget.data_classification}｜快照 ${String(approveTarget.snapshot_sha256).slice(0, 12)}…`" />
      <el-form label-width="90px" size="small">
        <el-form-item label="审批槽">
          <el-tag>{{ mySlot(approveTarget)?.slot_code }}</el-tag>
        </el-form-item>
        <el-form-item label="决定">
          <el-radio-group v-model="approveForm.decision">
            <el-radio-button value="APPROVE">批准</el-radio-button>
            <el-radio-button value="REJECT">驳回</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="意见">
          <el-input v-model="approveForm.comment" type="textarea" :rows="3"
            placeholder="写明核对过的字段映射、脱敏与预算结论" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="approveVisible = false">取消</el-button>
        <el-button type="primary" :loading="approving" @click="onApprove">提交决定</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="prepDrawer" title="准备单冻结事实" size="55%">
      <template v-if="prepDetail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="风险等级">{{ prepDetail.risk_level }}</el-descriptions-item>
          <el-descriptions-item label="数据分级">{{ prepDetail.data_classification }}</el-descriptions-item>
          <el-descriptions-item label="输入指纹">
            <span class="mono">{{ prepDetail.input_fingerprint }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="快照摘要">
            <span class="mono">{{ prepDetail.snapshot_sha256 }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <h4>变更资源范围</h4>
        <el-table :data="prepDetail.resources" size="small" border>
          <el-table-column prop="type" label="类型" width="130" />
          <el-table-column prop="ref" label="资源" />
          <el-table-column prop="access" label="访问" width="90" />
        </el-table>
        <h4>执行预算</h4>
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="读取行数">{{ prepDetail.budget?.max_read_rows }}</el-descriptions-item>
          <el-descriptions-item label="写入字节">{{ prepDetail.budget?.max_write_bytes }}</el-descriptions-item>
          <el-descriptions-item label="执行时长(ms)">{{ prepDetail.budget?.max_duration_ms }}</el-descriptions-item>
          <el-descriptions-item label="放大比">{{ prepDetail.budget?.max_amplification }}</el-descriptions-item>
          <el-descriptions-item label="拒绝率">{{ prepDetail.budget?.max_reject_rate }}</el-descriptions-item>
        </el-descriptions>
        <h4>回滚方案</h4>
        <ol class="steps">
          <li v-for="(s, i) in prepDetail.rollback_plan?.steps ?? []" :key="i">{{ s }}</li>
        </ol>
        <h4>审批决定</h4>
        <el-table :data="prepDetail.decisions" size="small" border>
          <el-table-column prop="approver_name" label="审批人" width="120" />
          <el-table-column prop="decision" label="决定" width="100" />
          <el-table-column prop="comment" label="意见" />
          <el-table-column prop="signature" label="签名" width="140" />
        </el-table>
      </template>
    </el-drawer>

    <el-drawer v-model="runDrawer" title="执行详情" size="62%">
      <template v-if="runDetail">
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item label="状态">{{ runDetail.status }}</el-descriptions-item>
          <el-descriptions-item label="读取">{{ runDetail.read_rows }}</el-descriptions-item>
          <el-descriptions-item label="写入">{{ runDetail.written_rows }}</el-descriptions-item>
          <el-descriptions-item label="分流">{{ runDetail.reject_rows }}</el-descriptions-item>
        </el-descriptions>

        <el-alert v-if="runDetail.failure" type="error" :closable="false" show-icon style="margin-top: 10px"
          :title="`失败快照 ${runDetail.failure.error_code}`" />

        <div v-if="runDetail.diagnosis" class="diagnosis">
          <h4>可解释根因</h4>
          <p>{{ runDetail.diagnosis.root_cause }}</p>
          <h4>修复建议</h4>
          <p>{{ runDetail.diagnosis.recommendation }}</p>
        </div>

        <h4>质量契约与分流</h4>
        <el-descriptions v-if="runDetail.quality_report" :column="4" border size="small">
          <el-descriptions-item label="结论">{{ runDetail.quality_report.status }}</el-descriptions-item>
          <el-descriptions-item label="有效行">{{ runDetail.quality_report.valid_rows }}</el-descriptions-item>
          <el-descriptions-item label="分流行">{{ runDetail.quality_report.rejected_rows }}</el-descriptions-item>
          <el-descriptions-item label="拒绝率">{{ runDetail.quality_report.reject_rate }}</el-descriptions-item>
          <el-descriptions-item label="监督决策">{{ runDetail.quality_report.supervision_decision }}</el-descriptions-item>
          <el-descriptions-item label="是否 Swap">{{ runDetail.quality_report.swapped ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="发布"><el-tag size="small">{{ runDetail.publication?.status }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="影子表"><span class="mono">{{ runDetail.publication?.shadow }}</span></el-descriptions-item>
        </el-descriptions>
        <el-table :data="runDetail.quality_report?.error_codes ?? []" size="small" border style="margin-top: 8px">
          <el-table-column prop="code" label="ErrorCode" width="240" />
          <el-table-column prop="count" label="条数" width="90" />
          <el-table-column prop="sample" label="样本摘要" />
        </el-table>

        <h4>监督事件</h4>
        <el-table :data="runDetail.supervision_events" size="small" border>
          <el-table-column prop="metric" label="指标" width="150" />
          <el-table-column prop="actual" label="实际" width="110" />
          <el-table-column prop="budget" label="预算" width="110" />
          <el-table-column prop="action" label="动作" width="120" />
          <el-table-column prop="message" label="说明" />
        </el-table>

        <h4>指标时序</h4>
        <el-table :data="runDetail.metrics" size="small" border>
          <el-table-column prop="captured_at" label="时间" width="220" />
          <el-table-column prop="read_rows" label="读取行" width="110" />
          <el-table-column prop="write_bytes" label="写入字节" width="120" />
          <el-table-column prop="throughput" label="吞吐" width="100" />
          <el-table-column prop="reject_rate" label="拒绝率" />
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { etlApi } from '@/api/etl'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const can = (cap: string) => auth.session?.capabilities.includes(cap) ?? false
const userId = () => auth.session?.user.id ?? ''

const tab = ref('prep')
const preparations = ref<Record<string, any>[]>([])
const runs = ref<Record<string, any>[]>([])
const loadingPrep = ref(false)
const loadingRuns = ref(false)
const approveVisible = ref(false)
const approving = ref(false)
const approveTarget = ref<Record<string, any> | null>(null)
const prepDrawer = ref(false)
const prepDetail = ref<Record<string, any> | null>(null)
const runDrawer = ref(false)
const runDetail = ref<Record<string, any> | null>(null)
const approveForm = reactive({ decision: 'APPROVE', comment: '' })

function mySlot(row: Record<string, any> | null) {
  return row?.slots?.find((s: any) => s.assignee_user_id === userId() && s.status === 'PENDING')
}

function statusType(status: string) {
  if (['SUCCEEDED', 'PUBLISHED'].includes(status)) return 'success'
  if (['ABORTED', 'FAILED'].includes(status)) return 'danger'
  if (status === 'ROLLED_BACK') return 'warning'
  return 'info'
}

async function loadPrep() {
  loadingPrep.value = true
  try {
    preparations.value = await etlApi.listPreparations()
  } finally {
    loadingPrep.value = false
  }
}

async function loadRuns() {
  loadingRuns.value = true
  try {
    runs.value = await etlApi.listRuns()
  } finally {
    loadingRuns.value = false
  }
}

function openApprove(row: Record<string, any>) {
  approveTarget.value = row
  approveForm.decision = 'APPROVE'
  approveForm.comment = ''
  approveVisible.value = true
}

async function onApprove() {
  if (!approveTarget.value) return
  approving.value = true
  try {
    await etlApi.approve(
      approveTarget.value.id,
      mySlot(approveTarget.value).slot_code,
      approveForm.decision,
      approveForm.comment
    )
    ElMessage.success('审批决定已记录并签名')
    approveVisible.value = false
    await loadPrep()
  } catch (e: any) {
    ElMessage.error(e.message ?? '审批失败')
  } finally {
    approving.value = false
  }
}

async function onCommit(row: Record<string, any>) {
  try {
    const data = await etlApi.commit(row.id)
    ElMessage.success(`已 Commit，Capability ${data.capability.jti.slice(0, 8)}…（5 分钟内单次有效）`)
    await Promise.all([loadPrep(), loadRuns()])
    tab.value = 'runs'
  } catch (e: any) {
    ElMessage.error(e.message ?? 'Commit 失败')
  }
}

async function onStart(row: Record<string, any>) {
  try {
    const data = await etlApi.startRun(row.id)
    if (data.status === 'SUCCEEDED') ElMessage.success('执行成功，已原子 Swap 发布')
    else ElMessage.warning(`执行${data.status}：${data.abort_reason ?? ''}`)
    await loadRuns()
    await openRun({ id: row.id })
  } catch (e: any) {
    ElMessage.error(e.message ?? '启动失败')
  }
}

async function openPrep(row: Record<string, any>) {
  prepDetail.value = await etlApi.getPreparation(row.id)
  prepDrawer.value = true
}

async function openRun(row: Record<string, any>) {
  runDetail.value = await etlApi.getRun(row.id)
  runDrawer.value = true
}

async function onRollback(row: Record<string, any>) {
  try {
    const { value } = await ElMessageBox.prompt('填写回滚原因（写入证据链）', '受管回滚', {
      inputPlaceholder: '超预算中断后清理影子表'
    })
    const data = await etlApi.rollbackRun(row.id, value)
    ElMessage.success(`已回滚：${data.status}`)
    await loadRuns()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.message ?? '回滚失败')
  }
}

onMounted(async () => {
  await Promise.all([loadPrep(), loadRuns()])
})
</script>

<style scoped>
.page { padding: 4px; }
.bar { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.muted { color: #9aa3af; font-size: 12px; }
.mono { font-family: Consolas, Monaco, monospace; font-size: 12px; }
.steps { font-size: 13px; color: #1d2129; padding-left: 18px; }
.diagnosis { background: #fff7ed; border: 1px solid #fed7aa; border-radius: 6px; padding: 10px 12px; margin: 10px 0; }
.diagnosis h4 { margin: 6px 0; font-size: 13px; }
.diagnosis p { margin: 0 0 6px; font-size: 13px; }
h4 { font-size: 13px; margin: 14px 0 8px; }
</style>
