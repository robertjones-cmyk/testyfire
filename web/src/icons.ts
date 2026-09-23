/**
 * Icon mapping.
 *
 * The Torch app uses Untitled UI names (`fire-02`, `security`, `equipment`,
 * `grass`, `weather-03`, `camera-01`, `sensor-color`, `search`, `settings-02`,
 * `chevron-*`, `x-close`). Lucide is the closest permissively licensed (ISC)
 * match, so each Torch name is mapped to its nearest Lucide component here.
 * Swap this file for `@untitled-ui/icons-vue` when the real icon set is
 * available — nothing else imports Lucide directly.
 */
import {
  AlertTriangle, Battery, Camera, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight,
  ChevronUp, CircleHelp, Cloud, Flame, Gauge, LayoutDashboard, Leaf, Map, Moon,
  Radio, Search, Settings, Shield, ShieldCheck, Sun, Thermometer, Wind, Wrench, X,
} from 'lucide-vue-next'

/** Torch icon name -> component. */
export const icons = {
  'fire-02': Flame,
  security: Shield,
  equipment: Wrench,
  grass: Leaf,
  'weather-03': Cloud,
  'camera-01': Camera,
  'sensor-color': Radio,
  search: Search,
  'settings-02': Settings,
  'chevron-down': ChevronDown,
  'chevron-up': ChevronUp,
  'chevron-left': ChevronLeft,
  'chevron-right': ChevronRight,
  'x-close': X,
  map: Map,
  dashboard: LayoutDashboard,
  'check-shield': ShieldCheck,
  'question-circle': CircleHelp,
  'alert-triangle': AlertTriangle,
  'check-circle': CheckCircle2,
  thermometer: Thermometer,
  wind: Wind,
  gauge: Gauge,
  battery: Battery,
  sun: Sun,
  moon: Moon,
} as const

export type IconName = keyof typeof icons

/** Data category -> icon, per the Torch mapping. */
export const categoryIcon: Record<string, IconName> = {
  Fire: 'fire-02',
  Security: 'security',
  Equipment: 'equipment',
  Vegetation: 'grass',
  Weather: 'weather-03',
  'Air quality': 'wind',
  Gas: 'gauge',
  Thermal: 'thermometer',
  Camera: 'camera-01',
}
