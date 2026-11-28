import { useState } from 'react'

import { ChevronIcon, PencilIcon } from '../../components/Icons'
import { Button } from '../../components/ui'
import { offsetsSummary, offsetTitle } from '../../lib/reminderTimes'

const PRESETS = [14, 7, 3, 1]
export const MAX_OFFSETS = 10

const frame = (checked: boolean) =>
  `flex items-stretch overflow-hidden rounded-xl border ${
    checked
      ? 'border-transparent bg-blue-50 text-blue-800 dark:bg-blue-950 dark:text-blue-200'
      : 'border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300'
  }`

function Mark({
  title,
  checked,
  disabled,
  onChange,
}: {
  title: string
  checked: boolean
  disabled?: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="flex min-h-14 flex-1 cursor-pointer items-center gap-3 px-4 font-semibold">
      <input
        type="checkbox"
        className="size-5 accent-blue-700"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      {title}
    </label>
  )
}

/** За сколько дней до срока напоминать: галочки, любое число можно заменить своим. */
export default function OffsetList({
  days,
  onDueDay,
  onChange,
}: {
  days: number[]
  onDueDay: boolean
  onChange: (days: number[], onDueDay: boolean) => void
}) {
  const [open, setOpen] = useState(true)
  const [options, setOptions] = useState(() =>
    [...new Set([...PRESETS, ...days])].sort((a, b) => b - a),
  )
  const [editing, setEditing] = useState<number | null>(null)
  const [text, setText] = useState('')
  const value = /^\d{1,3}$/.test(text) ? Number(text) : 0
  const valid = value >= 1 && value <= 365
  const full = days.length >= MAX_OFFSETS

  const replace = (old: number) => {
    setOptions(
      [...new Set(options.map((item) => (item === old ? value : item)))].sort((a, b) => b - a),
    )
    // изменённое число сразу отмечается: иначе его незачем было менять
    onChange([...new Set([...days.filter((item) => item !== old), value])], onDueDay)
    setEditing(null)
  }

  return (
    <section className="space-y-2">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <span>
          <span className="block font-semibold">За сколько дней до срока</span>
          <span className="block text-sm text-slate-500 dark:text-slate-400">
            {offsetsSummary(days, onDueDay)}
          </span>
        </span>
        <ChevronIcon className={`size-5 shrink-0 ${open ? '-rotate-90' : 'rotate-90'}`} />
      </button>
      {open && (
        <ul className="space-y-2">
          {options.map((item) => {
            const checked = days.includes(item)
            return (
              <li key={item}>
                {editing === item ? (
                  <form
                    className="flex flex-wrap items-center gap-2 rounded-xl border border-blue-600 p-2"
                    onSubmit={(event) => {
                      event.preventDefault()
                      if (valid) replace(item)
                    }}
                  >
                    <input
                      autoFocus
                      inputMode="numeric"
                      aria-label="За сколько дней"
                      className="w-24 rounded-lg border border-slate-300 bg-transparent px-3 py-2 dark:border-slate-600"
                      value={text}
                      onChange={(event) => setText(event.target.value)}
                    />
                    <Button type="submit" disabled={!valid}>
                      Готово
                    </Button>
                    <Button variant="secondary" onClick={() => setEditing(null)}>
                      Отмена
                    </Button>
                  </form>
                ) : (
                  <div className={frame(checked)}>
                    <Mark
                      title={offsetTitle(item)}
                      checked={checked}
                      disabled={!checked && full}
                      onChange={(next) =>
                        onChange(
                          next ? [...days, item] : days.filter((other) => other !== item),
                          onDueDay,
                        )
                      }
                    />
                    <button
                      type="button"
                      aria-label={`Изменить «${offsetTitle(item)}»`}
                      onClick={() => {
                        setEditing(item)
                        setText(String(item))
                      }}
                      className="flex w-16 items-center justify-center border-l border-slate-200 dark:border-slate-700"
                    >
                      <PencilIcon className="size-5" />
                    </button>
                  </div>
                )}
              </li>
            )
          })}
          <li className={frame(onDueDay)}>
            <Mark
              title="В день срока"
              checked={onDueDay}
              onChange={(next) => onChange(days, next)}
            />
          </li>
        </ul>
      )}
    </section>
  )
}
