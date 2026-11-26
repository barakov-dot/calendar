import { formatDate } from '../lib/company'
import { monthGrid, type Task, type Tone, toneOf } from '../lib/tasks'
import { TONE_STYLES } from '../lib/toneStyles'

const TONES: [Tone, string][] = [
  ['overdue', 'просрочено'],
  ['planned', 'запланировано'],
  ['closed', 'выполнено'],
  ['skipped', 'не требуется'],
]

/** Сетка месяца: в клетке дня — число задач каждого цвета. */
export default function MonthGrid({
  month,
  tasks,
  today,
  selected,
  onSelect,
}: {
  month: string
  tasks: Task[]
  today: string
  selected: string | null
  onSelect: (date: string) => void
}) {
  return (
    <>
      <table className="w-full table-fixed border-collapse text-center text-sm">
        <thead>
          <tr>
            {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((name) => (
              <th key={name} className="py-1 font-medium">
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {monthGrid(month).map((week, index) => (
            <tr key={index}>
              {week.map((date, column) => {
                const due = tasks.filter((task) => task.due_date === date)
                return (
                  <td
                    key={date ?? column}
                    className="h-16 border border-slate-200 p-0 align-top dark:border-slate-700"
                  >
                    {date && (
                      <button
                        type="button"
                        aria-label={`${formatDate(date)}: задач ${due.length}`}
                        aria-pressed={date === selected}
                        onClick={() => onSelect(date)}
                        className={`flex h-full w-full flex-col items-center gap-0.5 p-1 hover:bg-slate-100 dark:hover:bg-slate-800 ${date === selected ? 'ring-2 ring-blue-600 ring-inset' : ''}`}
                      >
                        <span className={date === today ? 'font-bold text-blue-600' : ''}>
                          {Number(date.slice(8))}
                        </span>
                        <span className="flex flex-wrap justify-center gap-0.5">
                          {TONES.map(([tone]) => {
                            const count = due.filter((t) => toneOf(t, today) === tone).length
                            return count ? (
                              <span key={tone} className={`rounded px-1 text-xs ${TONE_STYLES[tone]}`}>
                                {count}
                              </span>
                            ) : null
                          })}
                        </span>
                      </button>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex flex-wrap gap-2 text-xs">
        {TONES.map(([tone, title]) => (
          <span key={tone} className={`rounded px-2 py-0.5 ${TONE_STYLES[tone]}`}>
            {title}
          </span>
        ))}
      </div>
    </>
  )
}
