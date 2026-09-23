<script setup lang="ts">
/**
 * Mapbox GL map.
 *
 * Accessibility notes — a Mapbox canvas is hard to use with a screen reader or
 * keyboard, so:
 *   - the container is a labelled `role="region"`;
 *   - Mapbox's own keyboard pan/zoom stays ON;
 *   - zoom controls are enlarged to 44x44 in CSS (Mapbox ships 29px);
 *   - EVERY marker is also reachable from the synced list panel beside the map
 *     (see MapView.vue) — nothing is map-only;
 *   - `prefers-reduced-motion` turns off fly-to animations and marker pulsing;
 *   - the blind-spot layer is a HATCH PATTERN, not just a colour, and proposed
 *     sensors use a DASHED outline, so the layers are distinguishable without
 *     relying on colour.
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import mapboxgl from 'mapbox-gl'
import { api, type CameraSummary, type SensorSummary, type UiConfig } from '@/api'

const props = defineProps<{
  config: UiConfig
  cameras: CameraSummary[]
  sensors: SensorSummary[]
  focus: { kind: 'camera' | 'sensor'; id: string } | null
  layers: { cones: boolean; blindSpot: boolean; proposed: boolean; cameras: boolean; sensors: boolean }
}>()
const emit = defineEmits<{
  (event: 'select-camera', key: string): void
  (event: 'select-sensor', id: string): void
}>()

const container = ref<HTMLDivElement | null>(null)
const map = shallowRef<mapboxgl.Map | null>(null)
const markers: mapboxgl.Marker[] = []
const ready = ref(false)
const failure = ref('')

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

function hatchPattern(): { width: number; height: number; data: Uint8Array } {
  // A 45-degree hatch so the blind-spot layer is a PATTERN, not just a colour.
  const size = 12
  const data = new Uint8Array(size * size * 4)
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const index = (y * size + x) * 4
      const onStripe = (x + y) % 6 < 2
      data[index] = 60
      data[index + 1] = 70
      data[index + 2] = 78
      data[index + 3] = onStripe ? 190 : 40
    }
  }
  return { width: size, height: size, data }
}

async function addOverlays(instance: mapboxgl.Map) {
  // --- camera view cones ---------------------------------------------------
  try {
    const cones = await api.get<GeoJSON.FeatureCollection>('/api/camera-views')
    instance.addSource('cones', { type: 'geojson', data: cones })
    instance.addLayer({
      id: 'cones-fill',
      type: 'fill',
      source: 'cones',
      paint: { 'fill-color': '#5b8def', 'fill-opacity': 0.18 },
    })
    instance.addLayer({
      id: 'cones-line',
      type: 'line',
      source: 'cones',
      paint: { 'line-color': '#5b8def', 'line-width': 1.5, 'line-opacity': 0.8 },
    })
  } catch {
    /* cones are optional chrome */
  }

  // --- blind spot + proposed sensors --------------------------------------
  try {
    const report = await api.get<{ geojson: GeoJSON.FeatureCollection }>('/api/blindspot')
    const features = report.geojson.features

    const pattern = hatchPattern()
    if (!instance.hasImage('blind-hatch')) {
      instance.addImage('blind-hatch', pattern, { pixelRatio: 2 })
    }

    const blind = features.filter((f) => f.properties?.layer === 'blind_spot')
    instance.addSource('blind', { type: 'geojson', data: { type: 'FeatureCollection', features: blind } })
    instance.addLayer({
      id: 'blind-fill',
      type: 'fill',
      source: 'blind',
      paint: { 'fill-pattern': 'blind-hatch', 'fill-opacity': 0.75 },
    })

    const proposed = features.filter((f) => f.properties?.layer === 'proposed_sensor')
    instance.addSource('proposed', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: proposed },
    })
    instance.addLayer({
      id: 'proposed-line',
      type: 'line',
      source: 'proposed',
      paint: {
        'line-color': '#FF5B24',
        'line-width': 2,
        'line-dasharray': [2, 2],   // dashed: distinguishable without colour
      },
    })

    const corridor = features.filter((f) => f.properties?.layer === 'area_of_interest')
    instance.addSource('corridor', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: corridor },
    })
    instance.addLayer({
      id: 'corridor-line',
      type: 'line',
      source: 'corridor',
      paint: { 'line-color': '#1fa463', 'line-width': 2, 'line-opacity': 0.9 },
    })
  } catch {
    /* blind-spot layers are optional chrome; the text summary still shows */
  }
}

function drawMarkers(instance: mapboxgl.Map) {
  markers.forEach((marker) => marker.remove())
  markers.length = 0

  if (props.layers.cameras) {
    props.cameras
      .filter((camera) => camera.lat != null && camera.lon != null)
      .forEach((camera) => {
        const element = document.createElement('button')
        element.type = 'button'
        element.className = 'map-marker map-marker--camera'
        element.setAttribute('aria-label', `Camera ${camera.name}`)
        element.innerHTML =
          '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
          'stroke-width="2" aria-hidden="true"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 ' +
          '2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>'
        element.addEventListener('click', () => emit('select-camera', camera.key))
        markers.push(
          new mapboxgl.Marker({ element }).setLngLat([camera.lon as number, camera.lat as number]).addTo(instance),
        )
      })
  }

  if (props.layers.sensors) {
    props.sensors.forEach((sensor) => {
      const element = document.createElement('button')
      element.type = 'button'
      element.className = `map-marker map-marker--sensor map-marker--${sensor.status}`
      element.setAttribute('aria-label', `Sensor ${sensor.name}, status ${sensor.status}`)
      // Status is carried by a glyph as well as colour.
      element.textContent = sensor.status === 'alarm' ? '!' : sensor.status === 'elevated' ? '~' : '•'
      element.addEventListener('click', () => emit('select-sensor', sensor.id))
      markers.push(new mapboxgl.Marker({ element }).setLngLat([sensor.lon, sensor.lat]).addTo(instance))
    })
  }
}

function setLayerVisibility(instance: mapboxgl.Map) {
  const toggles: [string, boolean][] = [
    ['cones-fill', props.layers.cones],
    ['cones-line', props.layers.cones],
    ['blind-fill', props.layers.blindSpot],
    ['proposed-line', props.layers.proposed],
  ]
  toggles.forEach(([id, visible]) => {
    if (instance.getLayer(id)) {
      instance.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none')
    }
  })
}

onMounted(() => {
  if (!props.config.map.token) {
    failure.value =
      props.config.map.token_problem || 'MAPBOX_TOKEN is not set, so the map cannot load.'
    return
  }
  if (!container.value) return

  mapboxgl.accessToken = props.config.map.token
  const instance = new mapboxgl.Map({
    container: container.value,
    style: props.config.map.style,
    center: props.config.map.center,
    zoom: props.config.map.zoom,
    keyboard: true,          // keyboard pan/zoom stays on
    attributionControl: true,
  })
  instance.addControl(new mapboxgl.NavigationControl({ visualizePitch: false }), 'bottom-right')

  instance.on('load', async () => {
    await addOverlays(instance)
    drawMarkers(instance)
    setLayerVisibility(instance)
    ready.value = true
  })
  instance.on('error', (event) => {
    failure.value = event.error?.message ?? 'The map failed to load.'
  })
  map.value = instance
})

watch(
  () => [props.cameras, props.sensors, props.layers.cameras, props.layers.sensors],
  () => {
    if (map.value && ready.value) drawMarkers(map.value)
  },
  { deep: true },
)

watch(
  () => props.layers,
  () => {
    if (map.value && ready.value) setLayerVisibility(map.value)
  },
  { deep: true },
)

watch(
  () => props.focus,
  (focus) => {
    if (!focus || !map.value) return
    const target =
      focus.kind === 'camera'
        ? props.cameras.find((camera) => camera.key === focus.id)
        : props.sensors.find((sensor) => sensor.id === focus.id)
    if (!target || target.lat == null || target.lon == null) return
    const options = { center: [target.lon, target.lat] as [number, number], zoom: 13 }
    // Respect prefers-reduced-motion: jump instead of flying.
    if (reducedMotion) map.value.jumpTo(options)
    else map.value.flyTo({ ...options, speed: 0.9 })
  },
)

onBeforeUnmount(() => {
  markers.forEach((marker) => marker.remove())
  map.value?.remove()
})
</script>

<template>
  <div class="map-wrap">
    <div
      v-if="!failure"
      ref="container"
      class="map"
      role="region"
      aria-label="Map of cameras, sensors and events"
      tabindex="0"
    />
    <div v-else class="map map--fallback" role="region" aria-label="Map unavailable">
      <div class="map__message">
        <h3>Map unavailable</h3>
        <p>{{ failure }}</p>
        <p class="muted">
          Everything on the map is also in the list beside it, so nothing here is map-only.
        </p>
      </div>
    </div>
  </div>
</template>

<style>
/* Global (not scoped): Mapbox markers live outside this component's tree. */
.map-marker {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 2px solid var(--color-surface);
  box-shadow: 0 1px 4px oklch(0% 0 0 / 35%);
  cursor: pointer;
  font-weight: 700;
  font-size: 13px;
  padding: 0;
  color: #fff;
}
.map-marker:focus-visible { box-shadow: 0 0 0 3px var(--color-brand-600); outline: none; }
.map-marker--camera { background: oklch(35% .05 261.34); border-radius: 6px; }
.map-marker--nominal { background: oklch(45% .12 155.59); }
.map-marker--elevated { background: oklch(46% .115 62.11); }
.map-marker--alarm { background: oklch(47% .18 28.54); }
.map-marker--unknown { background: oklch(45% .01 214); }

/* Mapbox ships 29px controls; 44px is the comfortable target size. */
.mapboxgl-ctrl-group button {
  width: 44px !important;
  height: 44px !important;
}
.mapboxgl-ctrl-group button:focus-visible {
  box-shadow: 0 0 0 3px var(--color-brand-600) !important;
}
</style>

<style scoped>
.map-wrap { position: relative; height: 100%; min-height: 420px; }
.map { position: absolute; inset: 0; border-radius: var(--radius-card); overflow: hidden; }
.map:focus-visible { box-shadow: var(--focus-ring); }
.map--fallback {
  display: grid;
  place-items: center;
  background: var(--color-surface-sunken);
  border: 1px dashed var(--color-border-strong);
}
.map__message { text-align: center; max-width: 380px; padding: 24px; }
</style>
