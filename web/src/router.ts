import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true, title: 'Log in' } },
  { path: '/', name: 'map', component: () => import('@/views/MapView.vue'), meta: { title: 'Map' } },
  { path: '/events', name: 'events', component: () => import('@/views/EventsView.vue'), meta: { title: 'Events' } },
  { path: '/events/:id', name: 'event-detail', component: () => import('@/views/EventsView.vue'), meta: { title: 'Events' } },
  { path: '/sensors', name: 'sensors', component: () => import('@/views/SensorsView.vue'), meta: { title: 'Sensors' } },
  { path: '/cameras', name: 'cameras', component: () => import('@/views/CamerasView.vue'), meta: { title: 'Cameras' } },
  { path: '/dashboard', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: 'Dashboard' } },
  { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { title: 'Settings' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.ready) await auth.refresh()
  if (!to.meta.public && !auth.isAuthenticated) return { name: 'login', query: { next: to.fullPath } }
  if (to.name === 'login' && auth.isAuthenticated) return { name: 'map' }
  return true
})

router.afterEach((to) => {
  // Announce the page to screen readers by keeping the title accurate.
  document.title = `${String(to.meta.title ?? 'Torch')} · Torch Camera Fusion (Prototype)`
})
