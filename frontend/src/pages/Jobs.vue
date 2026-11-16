<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJson, postJson } from '../api'

const domains = ref([])
const domainId = ref(1)
const jobs = ref([])
const err = ref('')
const notice = ref(null)
const busy = ref(false)

async function refresh() {
  jobs.value = await getJson(`/api/jobs?domain_id=${domainId.value}`)
}

onMounted(async () => {
  try {
    domains.value = await getJson('/api/domains')
    if (domains.value.length) domainId.value = domains.value[0].id
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
})

async function run(step) {
  busy.value = true
  err.value = ''
  notice.value = null
  try {
    const url = step === '明细'
      ? '/api/jobs/paste-to-detail'
      : '/api/jobs/detail-to-summary'
    notice.value = await postJson(url, { domain_id: domainId.value })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

const gateFailed = computed(() => notice.value && notice.value.status !== '成功')
</script>
<template>
  <div>
    <h2>分层任务</h2>
    <p class="lead">按主题域推进：先贴源到明细，再明细到汇总。上游未就绪时任务直接失败，下游分层不会被改写。</p>
    <div class="toolbar">
      <label>
        主题域
        <select v-model.number="domainId" @change="refresh">
          <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </label>
      <button :disabled="busy" @click="run('明细')">跑贴源到明细</button>
      <button class="secondary" :disabled="busy" @click="run('汇总')">跑明细到汇总</button>
    </div>
    <p v-if="err" class="err">{{ err }}</p>
    <div v-if="notice" :class="gateFailed ? 'err' : 'ok-note'">
      <template v-if="gateFailed">
        <strong>{{ notice.fail_type || '任务失败' }}</strong>
        ：{{ notice.fail_reason || notice.message }}
        <span v-if="notice.upstream_job_id">（最近一次上游成功任务 #{{ notice.upstream_job_id }}）</span>
      </template>
      <template v-else>
        任务 #{{ notice.id }} 成功，写入 {{ notice.out_count }} 行。
      </template>
      <div v-if="notice.gate" class="gate-proof">
        闸判定依据：{{ notice.gate.basis }} ·
        上游计数：{{ notice.gate.upstream_count }} ·
        所引成功任务：{{ notice.gate.upstream_job_id ? '#' + notice.gate.upstream_job_id : '—' }} ·
        是否放行：{{ notice.gate.allowed ? '是' : '否' }}
        <template v-if="notice.gate.fail_code"> · 原因码：{{ notice.gate.fail_code }}</template>
      </div>
    </div>
    <div class="panel">
      <table>
        <thead>
          <tr><th>编号</th><th>步骤</th><th>状态</th><th>说明</th><th>输入</th><th>写入</th><th>剔除</th><th>闸失败原因</th><th>闸判定依据</th><th>闸上游计数</th><th>闸所引成功任务</th><th>闸放行</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="j in jobs" :key="j.id">
            <td>{{ j.id }}</td>
            <td>{{ j.step_label || j.step }}</td>
            <td :class="j.status === '成功' ? 'ok' : 'warn'">{{ j.status }}</td>
            <td>{{ j.message }}</td>
            <td>{{ j.in_count }}</td>
            <td>{{ j.out_count }}</td>
            <td>{{ j.drop_count }}</td>
            <td :class="j.fail_type ? 'warn' : ''">
              <template v-if="j.fail_type">
                <strong>{{ j.fail_type }}</strong>：{{ j.fail_reason }}
                <span v-if="j.fail_code" class="muted">（{{ j.fail_code }}）</span>
              </template>
              <span v-else class="muted">—</span>
            </td>
            <td>{{ j.gate ? j.gate.basis : '—' }}</td>
            <td>{{ j.gate ? j.gate.upstream_count : '—' }}</td>
            <td>
              <template v-if="j.gate && j.gate.upstream_job_id">#{{ j.gate.upstream_job_id }}</template>
              <span v-else class="muted">—</span>
            </td>
            <td :class="j.gate && !j.gate.allowed ? 'warn' : ''">
              <template v-if="j.gate">{{ j.gate.allowed ? '是' : '否' }}</template>
              <span v-else class="muted">—</span>
            </td>
            <td>{{ j.created_at }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!jobs.length" class="muted">还没有任务记录。</p>
    </div>
  </div>
</template>
