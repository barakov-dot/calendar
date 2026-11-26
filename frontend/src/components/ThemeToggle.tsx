import { type ThemeChoice, useTheme } from '../lib/theme'

const OPTIONS: [ThemeChoice, string, string][] = [
  ['light', '☀️', 'Светлая тема'],
  ['dark', '🌙', 'Ночная тема'],
  ['system', 'Авто', 'Тема как в системе'],
]

export default function ThemeToggle() {
  const [theme, choose] = useTheme()
  return (
    <div
      role="group"
      aria-label="Тема оформления"
      className="inline-flex rounded-lg border border-slate-200 p-0.5 dark:border-slate-700"
    >
      {OPTIONS.map(([value, icon, title]) => (
        <button
          key={value}
          type="button"
          title={title}
          aria-label={title}
          aria-pressed={theme === value}
          onClick={() => choose(value)}
          className={`rounded-md px-2 py-1 text-xs ${theme === value ? 'bg-slate-200 dark:bg-slate-700' : 'opacity-60 hover:opacity-100'}`}
        >
          {icon}
        </button>
      ))}
    </div>
  )
}
