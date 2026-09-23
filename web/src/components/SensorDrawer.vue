<script setup lang="ts">
/** Sensor detail: latest readings with sparklines, each with a readings table. */
import { computed, ref, watch } from 'vue'
import { NDrawer, NDrawerContent, NSpin } from 'naive-ui'
import Sparkline from './Sparkline.vue'
import TorchIcon from './TorchIcon.vue'
import { api, type SensorReading } from '@/api'

const props = defineProps<{ sensorId: string | null }>()
const emit = defineEmits<{ (event: 'close'): void }>()

interface SensorDetail {
  id: string; name: string; lat: number; lon: number; battery: number | null
  last_seen: string | null; readings: SensorReading[]; latest: SensorReading | null
}

const detail = ref<SensorDetail | null>(null)
const loading = ref(false)
const show = computed(() => props.sensorId !== null)

watch(
  () => props.sensorId,
  async (id) => {
    detail.value = null
    if (!id) return
    loading.value = true
    try {
      detail.value = await api.get<SensorDetail>(`/api/sensors/${encodeURIComponent(id)}?limit=40`)
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

const timeLabels = computed(() =>
  (detail.value?.readings ?? []).map((reading) =>
    new Date(reading.ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }),
  ),
)
const smokeSeries = computed(() => (detail.value?.readings ?? []).map((r) => r.smoke_index))
const tempSeries = computed(() => (detail.value?.readings ?? []).map((r) => r.temp_c))
const thermalSeries = computed(() => (detail.value?.readings ?? []).map((r) => r.thermal_delta_c))
</script>

<template>
  <NDrawer
    :show="show"
    :width="460"
    placement="right"
    :trap-focus="true"
    :auto-focus="true"
    @update:show="(value: boolean) => !value && emit('close')"
  >
    <NDrawerContent :title="detail?.name ?? 'Sensor'" closable>
      <NSpin :show="loading">
        <div v-if="detail" class="stack">
          <section aria-labelledby="sensor-latest-heading">
            <h3 id="sensor-latest-heading">Latest reading</h3>
            <dl class="facts">
              <div class="facts__row">
                <dt>Smoke / gas index</dt>
                <dd>{{ detail.latest?.smoke_index?.toFixed(0) ?? '—' }} <span class="muted">(PM2.5 + VOC)</span></dd>
              </div>
              <div class="facts__row">
                <dt>Thermal</dt>
                <dd>
                  {{ detail.latest?.thermal_delta_c?.toFixed(1) ?? '—' }}°C over ambient
                  <span v-if="detail.latest?.thermal_hotspot" class="warn">
                    <TorchIcon name="alert-triangle" :size="14" /> hotspot
                  </span>
                </dd>
              </div>
              <div class="facts__row">
                <dt>Temperature</dt>
                <dd>{{ detail.latest?.temp_c?.toFixed(1) ?? '—' }}°C</dd>
              </div>
              <div class="facts__row">
                <dt>Audio event</dt>
                <dd>{{ detail.latest?.audio_event ? 'Yes' : 'No' }}</dd>
              </div>
              <div class="facts__row">
                <dt>Battery</dt>
                <dd>{{ detail.battery?.toFixed(0) ?? '—' }}%</dd>
              </div>
              <div class="facts__row">
                <dt>Location</dt>
                <dd>{{ detail.lat.toFixed(5) }}, {{ detail.lon.toFixed(5) }}</dd>
              </div>
            </dl>
          </section>

          <section aria-labelledby="sensor-trends-heading" class="trends">
            <h3 id="sensor-trends-heading">Trends</h3>
            <Sparkline label="Smoke / gas index" :values="smokeSeries" :labels="timeLabels" />
            <Sparkline label="Thermal delta" unit="°C" :values="thermalSeries" :labels="timeLabels" />
            <Sparkline label="Temperature" unit="°C" :values="tempSeries" :labels="timeLabels" />
          </section>
        </div>
      </NSpin>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.facts { margin: 0; }
.facts__row { display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--color-divider); }
.facts__row dt { flex: 0 0 150px; color: var(--color-text-muted); font-size: 13px; margin: 0; }
.facts__row dd { margin: 0; font-size: 13px; }
.warn { display: inline-flex; align-items: center; gap: 4px; color: var(--color-warning-text); font-weight: 700; }
.trends { display: flex; flex-direction: column; gap: 20px; }
</style>
