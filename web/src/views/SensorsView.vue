<script setup lang="ts">
/** Sensors screen — table of Torch sensors with status and latest readings. */
import { computed, h, ref } from 'vue'
import { NDataTable } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import SensorDrawer from '@/components/SensorDrawer.vue'
import TorchIcon from '@/components/TorchIcon.vue'
import type { SensorSummary } from '@/api'
import { useLiveStore } from '@/stores/live'

const live = useLiveStore()
const openSensorId = ref<string | null>(null)

/** Status carries an icon + text, never colour alone. */
function statusCell(row: SensorSummary) {
  const map = {
    alarm: { icon: 'alert-triangle', text: 'Alarm', cls: 'status status--alarm' },
    elevated: { icon: 'wind', text: 'Elevated', cls: 'status status--elevated' },
    nominal: { icon: 'check-circle', text: 'Nominal', cls: 'status status--nominal' },
    unknown: { icon: 'question-circle', text: 'No data', cls: 'status status--unknown' },
  } as const
  const config = map[row.status] ?? map.unknown
  return h('span', { class: config.cls }, [
    h(TorchIcon, { name: config.icon, size: 14 }),
    h('span', config.text),
  ])
}

const columns = computed<DataTableColumns<SensorSummary>>(() => [
  { title: 'Sensor', key: 'name' },
  { title: 'Status', key: 'status', width: 130, render: statusCell },
  {
    title: 'Smoke / gas index',
    key: 'smoke',
    width: 150,
    render: (row) => row.latest?.smoke_index?.toFixed(0) ?? '—',
  },
  {
    title: 'Thermal Δ',
    key: 'thermal',
    width: 110,
    render: (row) => (row.latest ? `${row.latest.thermal_delta_c.toFixed(1)}°C` : '—'),
  },
  {
    title: 'Temp',
    key: 'temp',
    width: 100,
    render: (row) => (row.latest ? `${row.latest.temp_c.toFixed(1)}°C` : '—'),
  },
  {
    title: 'Battery',
    key: 'battery',
    width: 100,
    render: (row) => (row.battery == null ? '—' : `${row.battery.toFixed(0)}%`),
  },
  {
    title: 'Last seen',
    key: 'last_seen',
    width: 140,
    render: (row) =>
      row.last_seen ? new Date(row.last_seen).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '—',
  },
])

function rowProps(row: SensorSummary) {
  return {
    style: 'cursor: pointer',
    tabindex: 0,
    'aria-label': `Sensor ${row.name}, status ${row.status}, open details`,
    onClick: () => (openSensorId.value = row.id),
    onKeydown: (event: KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        openSensorId.value = row.id
      }
    },
  }
}
</script>

<template>
  <div class="stack">
    <section class="card" aria-labelledby="sensors-heading">
      <h2 id="sensors-heading">Torch sensors ({{ live.sensors.length }})</h2>
      <p class="muted">
        Readings come from the mock sensor source. Swap in the real platform API by setting
        <code>sensors.source: torch_api</code> in config.yaml.
      </p>
      <NDataTable
        :columns="columns"
        :data="live.sensors"
        :row-key="(row: SensorSummary) => row.id"
        :row-props="rowProps"
        :loading="live.loading"
        :bordered="false"
      />
    </section>

    <SensorDrawer :sensor-id="openSensorId" @close="openSensorId = null" />
  </div>
</template>

<style scoped>
:deep(.status) { display: inline-flex; align-items: center; gap: 6px; font-weight: 700; font-size: 12px; }
:deep(.status--alarm) { color: var(--color-error-text); }
:deep(.status--elevated) { color: var(--color-warning-text); }
:deep(.status--nominal) { color: var(--color-success-text); }
:deep(.status--unknown) { color: var(--color-text-muted); }
</style>
