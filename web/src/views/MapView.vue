<script setup lang="ts">
/**
 * Map screen — the default view.
 *
 * The map is paired with a synced list panel (tabs: Cameras, Sensors, Events).
 * Selecting in the list centres the map and opens the same drawer, so every
 * map action is available without touching the map.
 */
import { computed, onMounted, ref } from 'vue'
import { NCheckbox, NSpin, NTabPane, NTabs } from 'naive-ui'
import CameraDrawer from '@/components/CameraDrawer.vue'
import SensorDrawer from '@/components/SensorDrawer.vue'
import StatusChip from '@/components/StatusChip.vue'
import TorchIcon from '@/components/TorchIcon.vue'
import TorchMap from '@/components/TorchMap.vue'
import { api, type BlindSpotSummary } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useLiveStore } from '@/stores/live'

const auth = useAuthStore()
const live = useLiveStore()

const openCameraKey = ref<string | null>(null)
const openSensorId = ref<string | null>(null)
const focus = ref<{ kind: 'camera' | 'sensor'; id: string } | null>(null)
const blindSpot = ref<BlindSpotSummary | null>(null)

const layers = ref({ cameras: true, sensors: true, cones: true, blindSpot: true, proposed: true })

onMounted(async () => {
  try {
    const report = await api.get<{ summary: BlindSpotSummary }>('/api/blindspot')
    blindSpot.value = report.summary
  } catch {
    /* the map still works without the blind-spot summary */
  }
})

function selectCamera(key: string) {
  focus.value = { kind: 'camera', id: key }
  openCameraKey.value = key
}
function selectSensor(id: string) {
  focus.value = { kind: 'sensor', id }
  openSensorId.value = id
}

const locatedCameras = computed(() => live.cameras.filter((camera) => camera.lat != null))
const recentEvents = computed(() => live.events.slice(0, 25))
</script>

<template>
  <div class="map-view">
    <section class="map-view__map" aria-labelledby="map-heading">
      <h2 id="map-heading" class="visually-hidden">Map</h2>
      <TorchMap
        v-if="auth.config"
        :config="auth.config"
        :cameras="live.cameras"
        :sensors="live.sensors"
        :focus="focus"
        :layers="layers"
        @select-camera="selectCamera"
        @select-sensor="selectSensor"
      />

      <!-- Floating layer toggle card, top right. -->
      <div class="layers card card--float">
        <fieldset class="layers__set">
          <legend class="layers__legend">Layers</legend>
          <NCheckbox v-model:checked="layers.cameras">Cameras</NCheckbox>
          <NCheckbox v-model:checked="layers.sensors">Torch sensors</NCheckbox>
          <NCheckbox v-model:checked="layers.cones">Camera view cones</NCheckbox>
          <NCheckbox v-model:checked="layers.blindSpot">Blind spots (hatched)</NCheckbox>
          <NCheckbox v-model:checked="layers.proposed">Proposed sensors (dashed)</NCheckbox>
        </fieldset>
        <dl class="legend">
          <div><dt><span class="swatch swatch--camera" aria-hidden="true" /></dt><dd>Camera</dd></div>
          <div><dt><span class="swatch swatch--sensor" aria-hidden="true" /></dt><dd>Sensor (• ok, ~ elevated, ! alarm)</dd></div>
          <div><dt><span class="swatch swatch--cone" aria-hidden="true" /></dt><dd>View cone</dd></div>
          <div><dt><span class="swatch swatch--blind" aria-hidden="true" /></dt><dd>Blind spot (hatched)</dd></div>
          <div><dt><span class="swatch swatch--proposed" aria-hidden="true" /></dt><dd>Proposed sensor (dashed)</dd></div>
        </dl>
      </div>
    </section>

    <!-- The synced list: everything on the map, reachable without it. -->
    <aside class="map-view__list" aria-labelledby="list-heading">
      <h2 id="list-heading" class="visually-hidden">Map contents</h2>

      <div v-if="blindSpot" class="card blind-summary">
        <h3>Coverage</h3>
        <p>{{ blindSpot.headline }}</p>
        <p v-if="blindSpot.dem_is_synthetic" class="warn-text">
          <TorchIcon name="alert-triangle" :size="14" />
          Elevation data is synthetic (no network) — these numbers are illustrative only.
        </p>
      </div>

      <NTabs type="line" default-value="cameras" animated>
        <NTabPane name="cameras" :tab="`Cameras (${locatedCameras.length})`">
          <ul class="list">
            <li v-for="camera in live.cameras" :key="camera.key">
              <button type="button" class="list__item" @click="selectCamera(camera.key)">
                <TorchIcon name="camera-01" :size="16" />
                <span class="list__main">
                  <span class="list__title">{{ camera.name }}</span>
                  <span class="list__meta">
                    {{ camera.feed_id }}
                    <template v-if="camera.latest_frame?.score != null">
                      · score {{ camera.latest_frame.score.toFixed(2) }}
                    </template>
                    <template v-if="!camera.heading_known"> · heading unknown (360° radius)</template>
                  </span>
                </span>
              </button>
            </li>
          </ul>
        </NTabPane>

        <NTabPane name="sensors" :tab="`Sensors (${live.sensors.length})`">
          <ul class="list">
            <li v-for="sensor in live.sensors" :key="sensor.id">
              <button type="button" class="list__item" @click="selectSensor(sensor.id)">
                <TorchIcon name="sensor-color" :size="16" />
                <span class="list__main">
                  <span class="list__title">{{ sensor.name }}</span>
                  <span class="list__meta">
                    {{ sensor.status }} · smoke index
                    {{ sensor.latest?.smoke_index?.toFixed(0) ?? '—' }}
                  </span>
                </span>
              </button>
            </li>
          </ul>
        </NTabPane>

        <NTabPane name="events" :tab="`Events (${live.events.length})`">
          <ul class="list">
            <li v-for="event in recentEvents" :key="event.id">
              <RouterLink class="list__item" :to="`/events/${event.id}`">
                <span class="list__main">
                  <StatusChip :status="event.status" :demo="event.demo" />
                  <span class="list__meta">
                    {{ event.camera_name ?? event.sensor_name ?? 'Unknown source' }} ·
                    {{ new Date(event.ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) }}
                  </span>
                </span>
              </RouterLink>
            </li>
          </ul>
        </NTabPane>
      </NTabs>

      <NSpin v-if="live.loading" size="small" />
    </aside>

    <CameraDrawer :camera-key="openCameraKey" @close="openCameraKey = null" />
    <SensorDrawer :sensor-id="openSensorId" @close="openSensorId = null" />
  </div>
</template>

<style scoped>
.map-view {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 20px;
  height: calc(100vh - 150px);
  min-height: 520px;
}
.map-view__map { position: relative; min-height: 420px; }
.map-view__list { overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }

.layers {
  position: absolute; top: 16px; right: 16px; z-index: 5;
  padding: 14px 16px; max-width: 260px;
}
.layers__set { border: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.layers__legend { font-weight: 700; font-size: 13px; color: var(--color-text-strong); padding: 0 0 6px; }
.legend { margin: 12px 0 0; padding-top: 10px; border-top: 1px solid var(--color-divider); font-size: 11px; }
.legend > div { display: flex; align-items: center; gap: 8px; margin-bottom: 5px; }
.legend dt, .legend dd { margin: 0; }
.legend dd { color: var(--color-text-muted); }
.swatch { width: 16px; height: 12px; display: block; border-radius: 3px; }
.swatch--camera { background: oklch(35% .05 261.34); }
.swatch--sensor { background: oklch(45% .12 155.59); border-radius: 50%; width: 12px; }
.swatch--cone { background: oklch(67.46% .1414 261.34); opacity: .4; }
.swatch--blind {
  background: repeating-linear-gradient(45deg, var(--color-gray-700) 0 2px, transparent 2px 5px);
  border: 1px solid var(--color-border-strong);
}
.swatch--proposed { border: 2px dashed var(--color-brand); background: none; height: 14px; }

.blind-summary p { font-size: 13px; margin-bottom: 0; }
.warn-text {
  display: flex; align-items: center; gap: 6px; margin-top: 8px;
  color: var(--color-warning-text); font-weight: 700; font-size: 12px;
}

.list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.list__item {
  display: flex; align-items: center; gap: 10px; width: 100%;
  padding: 10px 12px; min-height: 44px;
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-control); cursor: pointer; text-align: left;
  color: var(--color-text-body); text-decoration: none; font: inherit;
}
.list__item:hover { background: var(--color-surface-sunken); text-decoration: none; }
.list__main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.list__title { font-weight: 700; color: var(--color-text-strong); font-size: 13px; }
.list__meta { font-size: 12px; color: var(--color-text-muted); }

/* At 320px wide / 200% zoom the map stacks under the list without losing content. */
@media (max-width: 1100px) {
  .map-view { grid-template-columns: 1fr; height: auto; }
  .map-view__map { height: 420px; }
  .layers { position: static; max-width: none; margin-top: 12px; }
}
</style>
