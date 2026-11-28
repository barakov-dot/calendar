export interface Declaration {
  company_id: number
  company_name: string
  inn: string
  title: string
  correction: number
  totals: { label: string; kopecks: number }[]
  parts: {
    task_id: number | null
    title: string
    due_date: string
    current_kopecks: number | null
    new_kopecks: number
    kept: string
  }[]
  warnings: string[]
  switches_to_monthly: boolean
  enables: string[]
}

export type Status = 'reading' | 'ready' | 'writing' | 'done' | 'failed'

export interface Item {
  id: number
  file: File
  status: Status
  // после записи — то, что сделано, до неё — предпросмотр
  data?: Declaration
  error?: Error
}

export const changesOf = (data: Declaration) => data.parts.filter((part) => !part.kept)

/** Почему файл нельзя записать вместе с остальными; пусто — можно.
 *
 * Один платёж могут менять исходная декларация и корректировка или два разных файла. */
export function blockedReason(item: Item, items: Item[]): string {
  if (item.status !== 'ready' || !item.data) return ''
  const mine = item.data
  for (const other of items) {
    const theirs = other.data
    if (other.id === item.id || !theirs || theirs.company_id !== mine.company_id) continue
    if (theirs.correction < mine.correction) continue
    const differs = changesOf(mine).some((part) =>
      changesOf(theirs).some(
        (rival) =>
          rival.title === part.title &&
          rival.due_date === part.due_date &&
          rival.new_kopecks !== part.new_kopecks,
      ),
    )
    if (!differs) continue
    return theirs.correction > mine.correction
      ? `Тот же платёж есть в более поздней корректировке («${other.file.name}»): этот файл в общую запись не войдёт.`
      : `Файл «${other.file.name}» меняет тот же платёж на другую сумму. Выберите нужный и впишите суммы из его карточки.`
  }
  return ''
}
