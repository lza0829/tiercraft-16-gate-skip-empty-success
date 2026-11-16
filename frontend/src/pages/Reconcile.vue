<script setup>
import { onMounted, ref } from 'vue'
import { getJson, postJson } from '../api'

const domains = ref([])
const domainId = ref(1)
const reports = ref([])
const err = ref('')
const busy = ref(false)

async function refresh() {
  reports.value = await getJson(`/api/reconcile?domain_id=${domainId.value}`)
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

async function run() {
  busy.value = true
  err.value = ''
  try {
    await postJson('/api/reconcile', { domain_id: domainId.value })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <div>
    <h2>层间对账</h2>
    <p class="lead">核对明细行数与汇总行数合计、金额是否一致。</p>
    <div class="toolbar">
      <label>
        主题域
        <select v-model.number="domainId" @change="refresh">
          <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </label>
      <button :disabled="busy" @click="run">生成对账报告</button>
    </div>
    <p v-if="err" class="err">{{ err }}</p>
    <div class="panel" v-for="r in reports" :key="r.id">
      <h3>
        报告 {{ r.id }}
        <span :class="r.status === '一致' ? 'ok' : 'warn'"> · {{ r.status }}</span>
      </h3>
      <table>
        <tbody>
          <tr><th>贴源行数</th><td>{{ r.detail.贴源行数 }}</td></tr>
          <tr><th>明细行数</th><td>{{ r.detail.明细行数 }}</td></tr>
          <tr><th>汇总行数合计</th><td>{{ r.detail.汇总行数合计 }}</td></tr>
          <tr><th>明细金额合计</th><td>{{ r.detail.明细金额合计 }}</td></tr>
          <tr><th>汇总金额合计</th><td>{{ r.detail.汇总金额合计 }}</td></tr>
          <tr><th>键对齐</th><td>{{ r.detail.键对齐 ? '是' : '否' }}</td></tr>
          <tr><th>金额漂移</th><td>{{ r.detail.金额漂移 }}</td></tr>
          <tr><th>生成时间</th><td>{{ r.created_at }}</td></tr>
        </tbody>
      </table>
    </div>
    <p v-if="!reports.length" class="muted">暂无对账报告。</p>
  </div>
</template>
