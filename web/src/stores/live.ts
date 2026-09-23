/**
 * Live data store.
 *
 * Polls the API and holds cameras, sensors and events. Two accessibility rules
 * are enforced here rather than in each view:
 *
 * 1. **Pause live updates** — polling stops entirely when paused, so an
 *    auto-refresh never moves the row a keyboard user is on.
 * 2. **Announcements** — a new event produces one announcement: `assertive`
 *    for Verified/Critical, `polite` otherwise. Frame refreshes are never
 *    announced.
 */
import { defineStore } from 'pinia'
import { api, type CameraSummary, type FeedHealth, type SensorSummary, type TorchEvent } from '@/api'

const POLL_INTERVAL_MS = 15_000

export const useLiveStore = defineStore('live', {
  state: () => ({
    cameras: [] as CameraSummary[],
    feeds: {} as Record<string, FeedHealth>,
    sensors: [] as SensorSummary[],
    events: [] as TorchEvent[],
    loading: false,
    error: '' as string,
    paused: false,
    lastUpdated: null as Date | null,
    announcement: '' as string,
    announcementPoliteness: 'polite' as 'polite' | 'assertive',
    seenEventIds: new Set<number>(),
    timer: null as ReturnType<typeof setInterval> | null,
    selection: null as { kind: 'camera' | 'sensor' | 'event'; id: string } | null,
  }),
  getters: {
    camerasByFeed(state): Record<string, CameraSummary[]> {
      return state.cameras.reduce<Record<string, CameraSummary[]>>((grouped, camera) => {
        ;(grouped[camera.feed_id] ??= []).push(camera)
        return grouped
      }, {})
    },
    openEvents: (state) => state.events.filter((event) => event.human_label === null),
  },
  actions: {
    async refreshAll(announce = true) {
      if (this.loading) return
      this.loading = true
      try {
        const [cameraData, sensorData, eventData] = await Promise.all([
          api.get<{ cameras: CameraSummary[]; feeds: Record<string, FeedHealth> }>('/api/cameras'),
          api.get<{ sensors: SensorSummary[] }>('/api/sensors'),
          api.get<{ events: TorchEvent[] }>('/api/events?limit=200'),
        ])
        this.cameras = cameraData.cameras
        this.feeds = cameraData.feeds
        this.sensors = sensorData.sensors
        if (announce) this.announceNew(eventData.events)
        this.events = eventData.events
        this.lastUpdated = new Date()
        this.error = ''
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Could not load data'
      } finally {
        this.loading = false
      }
    },

    announceNew(incoming: TorchEvent[]) {
      const first = this.seenEventIds.size === 0
      const fresh = incoming.filter((event) => !this.seenEventIds.has(event.id))
      incoming.forEach((event) => this.seenEventIds.add(event.id))
      if (first || fresh.length === 0) return

      const critical = fresh.find((event) => event.status === 'verified' || event.severity === 'Critical')
      if (critical) {
        this.announcementPoliteness = 'assertive'
        this.announcement =
          `Verified event ${critical.id}: ${critical.status_label}` +
          (critical.camera_name ? ` at ${critical.camera_name}` : '') +
          (critical.sensor_name ? `, confirmed by sensor ${critical.sensor_name}` : '')
        return
      }
      this.announcementPoliteness = 'polite'
      this.announcement =
        fresh.length === 1
          ? `New event: ${fresh[0].status_label}${fresh[0].camera_name ? ` at ${fresh[0].camera_name}` : ''}`
          : `${fresh.length} new events`
    },

    clearAnnouncement() {
      this.announcement = ''
    },

    startPolling() {
      this.stopPolling()
      this.timer = setInterval(() => {
        if (!this.paused) void this.refreshAll()
      }, POLL_INTERVAL_MS)
    },
    stopPolling() {
      if (this.timer) clearInterval(this.timer)
      this.timer = null
    },
    setPaused(paused: boolean) {
      this.paused = paused
      if (!paused) void this.refreshAll()
    },
    select(kind: 'camera' | 'sensor' | 'event', id: string) {
      this.selection = { kind, id }
    },
    clearSelection() {
      this.selection = null
    },
  },
})
