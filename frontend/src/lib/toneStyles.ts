import type { Tone } from './tasks'

export const TONE_STYLES: Record<Tone, string> = {
  overdue: 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200',
  planned: 'bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-200',
  closed: 'bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-200',
  skipped: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400',
}
