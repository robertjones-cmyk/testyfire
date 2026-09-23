import { defineStore } from 'pinia'
import { api, setCsrfToken, type UiConfig } from '@/api'

interface Me {
  email: string
  role: 'viewer' | 'operator' | 'admin'
  csrf_token: string
  idle_expires_at?: string
  session: { idle_timeout_minutes: number; absolute_timeout_minutes: number; idle_warning_seconds: number }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    email: '' as string,
    role: '' as '' | 'viewer' | 'operator' | 'admin',
    idleExpiresAt: null as string | null,
    idleWarningSeconds: 120,
    idleTimeoutMinutes: 30,
    ready: false,
    config: null as UiConfig | null,
  }),
  getters: {
    isAuthenticated: (state) => state.email !== '',
    isOperator: (state) => state.role === 'operator' || state.role === 'admin',
    isAdmin: (state) => state.role === 'admin',
  },
  actions: {
    applyMe(me: Me) {
      this.email = me.email
      this.role = me.role
      this.idleExpiresAt = me.idle_expires_at ?? null
      this.idleWarningSeconds = me.session.idle_warning_seconds
      this.idleTimeoutMinutes = me.session.idle_timeout_minutes
      setCsrfToken(me.csrf_token)
    },
    async login(email: string, password: string) {
      const result = await api.post<Me>('/api/auth/login', { email, password })
      this.applyMe(result)
      await this.loadConfig()
    },
    async refresh() {
      try {
        this.applyMe(await api.get<Me>('/api/auth/me'))
        await this.loadConfig()
      } catch {
        this.clear()
      } finally {
        this.ready = true
      }
    },
    async loadConfig() {
      this.config = await api.get<UiConfig>('/api/config/ui')
    },
    async extendSession() {
      const result = await api.post<{ session: Me['session'] }>('/api/auth/extend')
      this.idleTimeoutMinutes = result.session.idle_timeout_minutes
      this.touch()
    },
    touch() {
      this.idleExpiresAt = new Date(Date.now() + this.idleTimeoutMinutes * 60_000).toISOString()
    },
    async logout() {
      try {
        await api.post('/api/auth/logout')
      } finally {
        this.clear()
      }
    },
    clear() {
      this.email = ''
      this.role = ''
      this.config = null
      this.idleExpiresAt = null
      setCsrfToken('')
    },
  },
})
