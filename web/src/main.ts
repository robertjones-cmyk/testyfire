import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { useTheme } from './theme/useTheme'
import './styles/theme.css'
import 'mapbox-gl/dist/mapbox-gl.css'

useTheme().init()

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
