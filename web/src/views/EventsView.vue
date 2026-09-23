<script setup lang="ts">
/**
 * Events screen — a filterable table plus a detail drawer.
 *
 * Accessibility choices worth naming:
 *   - status is a chip with an icon AND text, never colour alone;
 *   - "Pause live updates" stops polling, so an auto-refresh can never move the
 *     row a keyboard user is working on;
 *   - the drawer traps focus, closes on Esc, and returns focus to the row that
 *     opened it.
 */
import { computed, h, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton, NDataTable, NDrawer, NDrawerContent, NSelect, NSpin, NSwitch, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import FrameImage from '@/components/FrameImage.vue'
import Sparkline from '@/components/Sparkline.vue'
import StatusChip from '@/components/StatusChip.vue'
import TorchIcon from '@/components/TorchIcon.vue'
import { api, type SensorReading, type TorchEvent } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useLiveStore } from '@/stores/live'

const auth = useAuthStore()
const live = useLiveStore()
const route = useRoute()
const router = useRouter()
const message = useMessage()

const statusFilter = ref<string | null>(null)
const severityFilter = ref<string | null>(null)
const cameraFilter = ref<string | null>(null)
const categoryFilter = ref<string | null>(null)

const openEventId = ref<number | null>(null)
const detail = ref<(TorchEvent & {
  confirming_reading?: SensorReading | null
  sensor_history?: SensorReading[]
  frame_strip?: { id: number; ts: string; score: number | null; view_changed: number }[]
  timeline?: { ts: string; text: string }[]
  dispatch_attempts?: { ts: string; url: string; attempt: number; status_code: number | null; ok: number }[]
}) | null>(null)
const detailLoading = ref(false)
const deciding = ref(false)
/** Where focus goes when the drawer closes. */
let lastTrigger: HTMLElement | null = null

const statusOptions = [
  { label: 'All statuses', value: '' },
  { label: 'Possible smoke', value: 'possible_smoke' },
  { label: 'Verified', value: 'verified' },
  { label: 'Sensor only', value: 'sensor_only' },
]
const severityOptions = [
  { label: 'All severities', value: '' },
  { label: 'Critical', value: 'Critical' },
  { label: 'Warning', value: 'Warning' },
]
const categoryOptions = [
  { label: 'All categories', value: '' },
  ...['Fire', 'Security', 'Equipment', 'Vegetation', 'Weather', 'Air quality', 'Gas', 'Thermal'].map(
    (name) => ({ label: name, value: name }),
  ),
]
const cameraOptions = computed(() => [
  { label: 'All cameras', value: '' },
  ...live.cameras.map((camera) => ({ label: camera.name, value: camera.key })),
])

const filtered = computed(() =>
  live.events.filter((event) => {
    if (statusFilter.value && event.status !== statusFilter.value) return false
    if (severityFilter.value && event.severity !== severityFilter.value) return false
    if (cameraFilter.value && event.camera_key !== cameraFilter.value) return false
    if (categoryFilter.value && event.category !== categoryFilter.value) return false
    return true
  }),
)

const columns = computed<DataTableColumns<TorchEvent>>(() => [
  {
    title: 'Status',
    key: 'status',
    width: 210,
    render: (row) => h(StatusChip, { status: row.status, demo: row.demo }),
  },
  { title: 'Severity', key: 'severity', width: 100 },
  { title: 'Category', key: 'category', width: 110 },
  {
    title: 'Source',
    key: 'source',
    render: (row) => row.camera_name ?? row.sensor_name ?? '—',
  },
  {
    title: 'Score',
    key: 'score',
    width: 90,
    render: (row) => (row.score == null ? '—' : row.score.toFixed(2)),
  },
  {
    title: 'Detected',
    key: 'ts',
    width: 160,
    render: (row) => new Date(row.ts).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' }),
  },
  {
    title: 'Operator decision',
    key: 'human_label',
    width: 150,
    render: (row) =>
      row.human_label === 'real' ? 'Real' : row.human_label === 'false_alarm' ? 'False alarm' : '—',
  },
])

function rowProps(row: TorchEvent) {
  return {
    style: 'cursor: pointer',
    tabindex: 0,
    'aria-label': `Event ${row.id}, ${row.status_label}, open details`,
    onClick: (event: MouseEvent) => {
      lastTrigger = event.currentTarget as HTMLElement
      void openEvent(row.id)
    },
    onKeydown: (event: KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        lastTrigger = event.currentTarget as HTMLElement
        void openEvent(row.id)
      }
    },
  }
}

async function openEvent(id: number) {
  openEventId.value = id
  detailLoading.value = true
  try {
    detail.value = await api.get(`/api/events/${id}`)
  } finally {
    detailLoading.value = false
  }
}

async function closeDrawer() {
  openEventId.value = null
  detail.value = null
  if (route.name === 'event-detail') await router.push('/events')
  await nextTick()
  lastTrigger?.focus()
}

async function decide(label: 'real' | 'false_alarm') {
  if (!openEventId.value) return
  deciding.value = true
  try {
    await api.post(`/api/events/${openEventId.value}/decision`, { label })
    message.success(label === 'real' ? 'Marked as real' : 'Marked as false alarm')
    await live.refreshAll(false)
    await openEvent(openEventId.value)
  } catch (error) {
    message.error(error instanceof Error ? error.message : 'Could not record the decision')
  } finally {
    deciding.value = false
  }
}

const smokeSeries = computed(() => (detail.value?.sensor_history ?? []).slice().reverse().map((r) => r.smoke_index))
const smokeLabels = computed(() =>
  (detail.value?.sensor_history ?? [])
    .slice()
    .reverse()
    .map((r) => new Date(r.ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })),
)

onMounted(() => {
  if (route.params.id) void openEvent(Number(route.params.id))
})
watch(
  () => route.params.id,
  (id) => {
    if (id) void openEvent(Number(id))
  },
)
</script>

<template>
  <div class="stack">
    <section class="card filters" aria-labelledby="filters-heading">
      <h2 id="filters-heading" class="visually-hidden">Filters</h2>
      <div class="filters__grid">
        <div class="filter">
          <span class="filter__label" id="filter-status-label">Status</span>
          <NSelect v-model:value="statusFilter" :options="statusOptions" clearable
            aria-labelledby="filter-status-label" />
        </div>
        <div class="filter">
          <span class="filter__label" id="filter-severity-label">Severity</span>
          <NSelect v-model:value="severityFilter" :options="severityOptions" clearable
            aria-labelledby="filter-severity-label" />
        </div>
        <div class="filter">
          <span class="filter__label" id="filter-category-label">Category</span>
          <NSelect v-model:value="categoryFilter" :options="categoryOptions" clearable
            aria-labelledby="filter-category-label" />
        </div>
        <div class="filter">
          <span class="filter__label" id="filter-camera-label">Camera</span>
          <!-- `filterable` renders an internal search <input>; aria-labelledby on
               the wrapper does not reach it, so label it through input-props. -->
          <NSelect
            v-model:value="cameraFilter"
            :options="cameraOptions"
            clearable
            filterable
            aria-labelledby="filter-camera-label"
            :input-props="{ 'aria-label': 'Filter by camera' }"
          />
        </div>
        <div class="filter filter--pause">
          <span class="filter__label" id="pause-live-label">Pause live updates</span>
          <NSwitch
            :value="live.paused"
            aria-labelledby="pause-live-label"
            @update:value="live.setPaused($event as boolean)"
          />
          <span class="filter__hint">{{ live.paused ? 'Paused — the table will not move.' : 'Refreshing every 15s.' }}</span>
        </div>
      </div>
    </section>

    <section class="card" aria-labelledby="events-heading">
      <h2 id="events-heading">Events ({{ filtered.length }})</h2>
      <NDataTable
        :columns="columns"
        :data="filtered"
        :row-key="(row: TorchEvent) => row.id"
        :row-props="rowProps"
        :loading="live.loading"
        :pagination="{ pageSize: 20 }"
        :bordered="false"
      />
    </section>

    <NDrawer
      :show="openEventId !== null"
      :width="520"
      placement="right"
      :trap-focus="true"
      :auto-focus="true"
      @update:show="(value: boolean) => !value && closeDrawer()"
    >
      <NDrawerContent :title="`Event ${openEventId ?? ''}`" closable>
        <NSpin :show="detailLoading">
          <div v-if="detail" class="stack">
            <StatusChip :status="detail.status" :demo="detail.demo" />

            <FrameImage
              v-if="detail.frame_id"
              :frame-id="detail.frame_id"
              :camera-name="detail.camera_name ?? 'Camera'"
              :captured-at="detail.ts"
              :score="detail.score"
              :bbox="detail.bbox"
            />

            <section v-if="detail.confirmation_detail" aria-labelledby="confirm-heading">
              <h3 id="confirm-heading">Sensor confirmation</h3>
              <p>{{ detail.confirmation_detail }}</p>
              <dl v-if="detail.confirming_reading" class="facts">
                <div class="facts__row">
                  <dt>Smoke / gas index</dt>
                  <dd>{{ detail.confirming_reading.smoke_index?.toFixed(0) }}</dd>
                </div>
                <div class="facts__row">
                  <dt>Thermal delta</dt>
                  <dd>{{ detail.confirming_reading.thermal_delta_c?.toFixed(1) }}°C</dd>
                </div>
                <div class="facts__row">
                  <dt>Reading time</dt>
                  <dd>{{ new Date(detail.confirming_reading.ts).toLocaleString() }}</dd>
                </div>
              </dl>
              <Sparkline
                v-if="smokeSeries.length > 1"
                label="Confirming sensor — smoke index"
                :values="smokeSeries"
                :labels="smokeLabels"
              />
            </section>

            <section v-if="detail.timeline?.length" aria-labelledby="timeline-heading">
              <h3 id="timeline-heading">Timeline</h3>
              <ol class="timeline">
                <li v-for="(step, index) in detail.timeline" :key="index">
                  <span class="timeline__time">{{ new Date(step.ts).toLocaleTimeString() }}</span>
                  <span>{{ step.text }}</span>
                </li>
              </ol>
            </section>

            <section v-if="detail.dispatch_attempts?.length" aria-labelledby="dispatch-heading">
              <h3 id="dispatch-heading">Dispatch</h3>
              <ul class="plain">
                <li v-for="(attempt, index) in detail.dispatch_attempts" :key="index">
                  Attempt {{ attempt.attempt }} → {{ attempt.url }} ·
                  {{ attempt.ok ? `delivered (${attempt.status_code})` : 'failed' }}
                </li>
              </ul>
            </section>
            <p v-else-if="detail.status === 'possible_smoke'" class="muted">
              Not dispatched: <strong>possible smoke</strong> events stay in the dashboard until a
              Torch sensor agrees.
            </p>

            <section aria-labelledby="decision-heading">
              <h3 id="decision-heading">Operator decision</h3>
              <p v-if="detail.human_label">
                Marked <strong>{{ detail.human_label === 'real' ? 'Real' : 'False alarm' }}</strong>
                by {{ detail.human_by }}
                on {{ detail.human_at ? new Date(detail.human_at).toLocaleString() : '' }}.
              </p>
              <div v-if="auth.isOperator" class="decision">
                <NButton :loading="deciding" @click="decide('real')">
                  <template #icon><TorchIcon name="check-circle" /></template>
                  Real
                </NButton>
                <NButton :loading="deciding" @click="decide('false_alarm')">
                  <template #icon><TorchIcon name="x-close" /></template>
                  False alarm
                </NButton>
              </div>
              <p v-else class="muted">
                Your role is <strong>{{ auth.role }}</strong>. Only operators and admins can record a
                decision.
              </p>
            </section>
          </div>
        </NSpin>
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<style scoped>
.filters__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }
.filter__label { display: block; font-size: 13px; font-weight: 700; color: var(--color-text-strong); margin-bottom: 6px; }
.filter__hint { display: block; font-size: 12px; color: var(--color-text-muted); margin-top: 6px; }
.filter--pause { display: flex; flex-direction: column; align-items: flex-start; }
.facts__row { display: flex; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--color-divider); }
.facts__row dt { flex: 0 0 150px; color: var(--color-text-muted); font-size: 13px; margin: 0; }
.facts__row dd { margin: 0; font-size: 13px; }
.timeline { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.timeline li { display: flex; gap: 12px; font-size: 13px; }
.timeline__time { color: var(--color-text-muted); flex: 0 0 90px; }
.plain { list-style: none; margin: 0; padding: 0; font-size: 13px; }
.decision { display: flex; gap: 12px; margin-top: 8px; }
</style>
