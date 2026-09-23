<script setup lang="ts">
/** Settings — read-only feed list, demo controls (admin), audit log (admin). */
import { onMounted, ref } from 'vue'
import { NButton, NDataTable, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import HealthDot from '@/components/HealthDot.vue'
import TorchIcon from '@/components/TorchIcon.vue'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useLiveStore } from '@/stores/live'

const auth = useAuthStore()
const live = useLiveStore()
const message = useMessage()

interface FeedRow {
  id: string; type: string; enabled: boolean; interval_s: number | null
  camera_count: number; reachable: boolean; last_success: string | null
  error_count: number; last_error: string | null
}
interface AuditRow {
  id: number; ts: string; actor_email: string | null; actor_role: string | null
  action: string; target: string | null; detail: string | null; ip: string | null
}

const feeds = ref<FeedRow[]>([])
const audit = ref<AuditRow[]>([])
const scenarioRunning = ref(false)

const feedColumns: DataTableColumns<FeedRow> = [
  { title: 'Feed', key: 'id' },
  { title: 'Type', key: 'type', width: 130 },
  {
    title: 'Enabled',
    key: 'enabled',
    width: 100,
    render: (row) => (row.enabled ? 'Yes' : 'No'),
  },
  { title: 'Cameras', key: 'camera_count', width: 100 },
  { title: 'Interval', key: 'interval_s', width: 100, render: (row) => `${row.interval_s ?? '—'}s` },
  {
    title: 'Last success',
    key: 'last_success',
    width: 160,
    render: (row) => (row.last_success ? new Date(row.last_success).toLocaleString() : 'never'),
  },
  { title: 'Errors', key: 'error_count', width: 90 },
  { title: 'Last error', key: 'last_error', render: (row) => row.last_error ?? '—' },
]

const auditColumns: DataTableColumns<AuditRow> = [
  {
    title: 'When',
    key: 'ts',
    width: 170,
    render: (row) => new Date(row.ts).toLocaleString(),
  },
  { title: 'Who', key: 'actor_email', width: 200, render: (row) => row.actor_email ?? 'system' },
  { title: 'Role', key: 'actor_role', width: 100, render: (row) => row.actor_role ?? '—' },
  { title: 'Action', key: 'action', width: 190 },
  { title: 'Target', key: 'target', render: (row) => row.target ?? '—' },
]

async function load() {
  feeds.value = (await api.get<{ feeds: FeedRow[] }>('/api/feeds')).feeds
  if (auth.isAdmin) {
    audit.value = (await api.get<{ entries: AuditRow[] }>('/api/admin/audit?limit=100')).entries
  }
}

async function runFireScenario() {
  scenarioRunning.value = true
  try {
    const result = await api.post<{ sensor_id: string; note: string }>('/api/admin/demo/fire-scenario')
    message.success(`Fire scenario running on ${result.sensor_id}. ${result.note}`)
    await live.refreshAll(false)
    await load()
  } catch (error) {
    message.error(error instanceof Error ? error.message : 'Could not start the scenario')
  } finally {
    scenarioRunning.value = false
  }
}

async function stopScenario() {
  await api.post('/api/admin/demo/fire-scenario/stop')
  message.info('Fire scenario stopped')
  await load()
}

async function pollNow() {
  const result = await api.post<{ frames_stored: number }>('/api/admin/ingest/poll-now')
  message.success(`Ingest cycle complete: ${result.frames_stored} frame(s) stored`)
  await live.refreshAll(false)
}

onMounted(load)
</script>

<template>
  <div class="stack">
    <section class="card" aria-labelledby="feeds-heading">
      <h2 id="feeds-heading">Feeds</h2>
      <p class="muted">
        Read-only. Feeds are configured in <code>config.yaml</code>; add a new one by following
        <code>docs/ADDING_A_FEED.md</code>, then validate it with
        <code>python -m feeds test &lt;feed_id&gt;</code>.
      </p>
      <NDataTable
        :columns="feedColumns"
        :data="feeds"
        :row-key="(row: FeedRow) => row.id"
        :bordered="false"
      />
      <ul class="feed-health">
        <li v-for="feed in feeds" :key="feed.id">
          <HealthDot :ok="feed.enabled ? feed.reachable : null" :label-prefix="`${feed.id}: `" />
        </li>
      </ul>
    </section>

    <section v-if="auth.isAdmin" class="card" aria-labelledby="demo-heading">
      <h2 id="demo-heading">Demo</h2>
      <p class="muted">
        The fire scenario ramps one mock sensor so a <strong>possible smoke</strong> camera event can
        be upgraded to <strong>verified</strong>. Everything it creates is tagged
        <code>demo</code>, shows a DEMO badge, and is dispatched only to the local test receiver —
        never to a real dispatch URL.
      </p>
      <div class="actions">
        <NButton type="primary" :loading="scenarioRunning" @click="runFireScenario">
          <template #icon><TorchIcon name="fire-02" /></template>
          Run fire scenario
        </NButton>
        <NButton @click="stopScenario">Stop scenario</NButton>
        <NButton @click="pollNow">Poll all cameras now</NButton>
      </div>
    </section>

    <section v-if="auth.isAdmin" class="card" aria-labelledby="audit-heading">
      <h2 id="audit-heading">Audit log</h2>
      <p class="muted">Logins, failed logins, alert decisions, config changes and demo triggers.</p>
      <NDataTable
        :columns="auditColumns"
        :data="audit"
        :row-key="(row: AuditRow) => row.id"
        :pagination="{ pageSize: 15 }"
        :bordered="false"
      />
    </section>

    <section v-else class="card">
      <h2>Account</h2>
      <p>
        Signed in as <strong>{{ auth.email }}</strong> with the
        <strong>{{ auth.role }}</strong> role. Feed, threshold and user management require the admin
        role.
      </p>
    </section>
  </div>
</template>

<style scoped>
.actions { display: flex; gap: 12px; flex-wrap: wrap; }
.feed-health { list-style: none; margin: 16px 0 0; padding: 0; display: flex; gap: 16px; flex-wrap: wrap; }
</style>
