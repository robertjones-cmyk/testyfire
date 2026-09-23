<script setup lang="ts">
/** Dashboard — kill-criteria KPIs and the blind-spot summary. */
import { computed, onMounted, ref } from 'vue'
import { NDataTable, NSpin } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import TorchIcon from '@/components/TorchIcon.vue'
import { api, type BlindSpotSummary } from '@/api'

interface CameraMetric {
  camera_name: string; feed_id: string; frames_ingested: number; frames_failed: number
  view_changes: number; possible_smoke_alerts: number; verified_alerts: number
  marked_false_alarm: number; marked_real: number; avg_inference_ms: number
  avg_cost_per_frame_usd: number; total_cost_usd: number; red: boolean; red_reasons: string[]
}
interface Totals {
  day: string; cameras: number; frames_ingested: number; frames_failed: number
  view_changes: number; possible_smoke_alerts: number; verified_alerts: number
  sensor_only_alerts: number; marked_false_alarm: number; false_alarm_rate: number
  avg_cost_per_frame_usd: number; total_cost_usd: number; cost_target_usd: number
  red_cameras: string[]
  thresholds: { max_false_alarms_per_camera_per_day: number; max_view_changes_per_camera_per_day: number }
}

const totals = ref<Totals | null>(null)
const perCamera = ref<CameraMetric[]>([])
const blindSpot = ref<BlindSpotSummary | null>(null)
const accuracyNote = ref('')
const loading = ref(true)

onMounted(async () => {
  try {
    const [metrics, blind] = await Promise.all([
      api.get<{ totals: Totals; per_camera: CameraMetric[] }>('/api/metrics/today'),
      api.get<{ summary: BlindSpotSummary; accuracy_note: string }>('/api/blindspot'),
    ])
    totals.value = metrics.totals
    perCamera.value = metrics.per_camera
    blindSpot.value = blind.summary
    accuracyNote.value = blind.accuracy_note
  } finally {
    loading.value = false
  }
})

const costOnTarget = computed(
  () => !!totals.value && totals.value.avg_cost_per_frame_usd <= totals.value.cost_target_usd,
)

const columns = computed<DataTableColumns<CameraMetric>>(() => [
  { title: 'Camera', key: 'camera_name' },
  { title: 'Feed', key: 'feed_id', width: 120 },
  { title: 'Frames', key: 'frames_ingested', width: 90 },
  { title: 'Failed', key: 'frames_failed', width: 90 },
  { title: 'View changes', key: 'view_changes', width: 120 },
  { title: 'Possible smoke', key: 'possible_smoke_alerts', width: 140 },
  { title: 'False alarms', key: 'marked_false_alarm', width: 120 },
  { title: 'Verified', key: 'verified_alerts', width: 100 },
  {
    title: 'Cost / frame',
    key: 'avg_cost_per_frame_usd',
    width: 130,
    render: (row) => `$${row.avg_cost_per_frame_usd.toFixed(6)}`,
  },
  {
    title: 'Kill criteria',
    key: 'red',
    width: 160,
    render: (row) =>
      row.red
        ? row.red_reasons.join('; ')
        : 'Within limits',
  },
])

function rowClass(row: CameraMetric) {
  return row.red ? 'row--red' : ''
}
</script>

<template>
  <NSpin :show="loading">
    <div class="stack">
      <section aria-labelledby="kpi-heading">
        <h2 id="kpi-heading">Kill-criteria metrics — {{ totals?.day }}</h2>
        <ul class="kpis">
          <li class="card kpi">
            <span class="kpi__label">Frames ingested</span>
            <span class="kpi__value">{{ totals?.frames_ingested ?? 0 }}</span>
            <span class="kpi__meta">{{ totals?.frames_failed ?? 0 }} failed</span>
          </li>
          <li class="card kpi">
            <span class="kpi__label">Possible smoke</span>
            <span class="kpi__value">{{ totals?.possible_smoke_alerts ?? 0 }}</span>
            <span class="kpi__meta">dashboard only — never dispatched</span>
          </li>
          <li class="card kpi">
            <span class="kpi__label">Verified</span>
            <span class="kpi__value">{{ totals?.verified_alerts ?? 0 }}</span>
            <span class="kpi__meta">camera + sensor agreed</span>
          </li>
          <li class="card kpi">
            <span class="kpi__label">Sensor only</span>
            <span class="kpi__value">{{ totals?.sensor_only_alerts ?? 0 }}</span>
            <span class="kpi__meta">no camera corroboration</span>
          </li>
          <li class="card kpi">
            <span class="kpi__label">False alarms (human-marked)</span>
            <span class="kpi__value">{{ totals?.marked_false_alarm ?? 0 }}</span>
            <span class="kpi__meta">
              limit {{ totals?.thresholds.max_false_alarms_per_camera_per_day }} per camera per day
            </span>
          </li>
          <li class="card kpi">
            <span class="kpi__label">View changes</span>
            <span class="kpi__value">{{ totals?.view_changes ?? 0 }}</span>
            <span class="kpi__meta">
              limit {{ totals?.thresholds.max_view_changes_per_camera_per_day }} per camera per day
            </span>
          </li>
          <li class="card kpi">
            <span class="kpi__label">Avg cost per frame</span>
            <span class="kpi__value">${{ totals?.avg_cost_per_frame_usd?.toFixed(6) ?? '0.000000' }}</span>
            <span class="kpi__meta">
              <TorchIcon :name="costOnTarget ? 'check-circle' : 'alert-triangle'" :size="13" />
              target ${{ totals?.cost_target_usd?.toFixed(3) }}
            </span>
          </li>
        </ul>

        <p v-if="totals?.red_cameras?.length" class="red-banner" role="status">
          <TorchIcon name="alert-triangle" :size="16" />
          Cameras over a kill-criteria threshold: {{ totals.red_cameras.join(', ') }}
        </p>
      </section>

      <section class="card" aria-labelledby="blind-heading">
        <h2 id="blind-heading">Blind-spot summary</h2>
        <p v-if="blindSpot" class="headline">{{ blindSpot.headline }}</p>
        <dl v-if="blindSpot" class="facts">
          <div class="facts__row"><dt>Area of interest</dt><dd>{{ blindSpot.area_of_interest }}</dd></div>
          <div class="facts__row"><dt>Corridor</dt><dd>{{ blindSpot.corridor_acres.toFixed(0) }} acres</dd></div>
          <div class="facts__row"><dt>Seen by cameras</dt><dd>{{ blindSpot.seen_acres.toFixed(0) }} acres ({{ blindSpot.coverage_percent }}%)</dd></div>
          <div class="facts__row"><dt>Blind</dt><dd>{{ blindSpot.blind_acres.toFixed(0) }} acres</dd></div>
          <div class="facts__row"><dt>Proposed sensors</dt><dd>{{ blindSpot.proposed_sensors }} covering {{ blindSpot.proposed_coverage_acres.toFixed(0) }} acres</dd></div>
          <div class="facts__row"><dt>Hardware cost</dt><dd>${{ blindSpot.hardware_cost_usd.toLocaleString() }}</dd></div>
          <div class="facts__row"><dt>Elevation source</dt><dd>{{ blindSpot.dem_source }}</dd></div>
          <div class="facts__row"><dt>Cameras used</dt><dd>{{ blindSpot.cameras_used }}</dd></div>
        </dl>
        <p class="muted note">{{ accuracyNote }}</p>
        <p>
          <a href="/api/blindspot/proposals.csv" download>Download proposed placements (CSV)</a>
          ·
          <a href="/api/metrics/daily.csv" download>Download today's kill-criteria CSV</a>
        </p>
      </section>

      <section class="card" aria-labelledby="per-camera-heading">
        <h2 id="per-camera-heading">Per camera, today</h2>
        <NDataTable
          :columns="columns"
          :data="perCamera"
          :row-key="(row: CameraMetric) => row.camera_name"
          :row-class-name="rowClass"
          :bordered="false"
        />
      </section>
    </div>
  </NSpin>
</template>

<style scoped>
.kpis {
  list-style: none; margin: 0; padding: 0;
  display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 16px;
}
.kpi { display: flex; flex-direction: column; gap: 4px; }
.kpi__label { font-size: 12px; color: var(--color-text-muted); font-weight: 700; }
.kpi__value { font-size: 26px; font-weight: 700; color: var(--color-text-strong); }
.kpi__meta { font-size: 12px; color: var(--color-text-muted); display: flex; align-items: center; gap: 4px; }
.red-banner {
  display: flex; align-items: center; gap: 8px; margin-top: 16px;
  background: oklch(94% .04 28.54); color: var(--color-error-text);
  border: 1px solid oklch(80% .1 28.54); border-radius: var(--radius-control);
  padding: 10px 12px; font-weight: 700; font-size: 13px;
}
:global([data-theme='dark']) .red-banner { background: oklch(30% .07 28.54); border-color: oklch(45% .12 28.54); }
.headline { font-size: 15px; font-weight: 700; color: var(--color-text-strong); }
.facts__row { display: flex; gap: 12px; padding: 7px 0; border-bottom: 1px solid var(--color-divider); }
.facts__row dt { flex: 0 0 180px; color: var(--color-text-muted); font-size: 13px; margin: 0; }
.facts__row dd { margin: 0; font-size: 13px; }
.note { font-size: 12px; margin-top: 12px; }
:deep(.row--red td) { background: oklch(97% .02 28.54); }
:global([data-theme='dark']) :deep(.row--red td) { background: oklch(26% .04 28.54); }
</style>
