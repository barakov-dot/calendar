import { useRef, useState } from 'react'
import { Link } from 'react-router'

import FileDrop from '../../components/FileDrop'
import { Alert, Button, Card, ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDate, formatKopecks } from '../../lib/company'
import { useRefreshTasks } from '../../lib/useTasks'
import { blockedReason, changesOf, type Declaration, type Item, type Status } from './batch'

/** Загрузка деклараций: суммы платежей берутся из XML и записываются после проверки. */
export default function Declarations() {
  const [items, setItems] = useState<Item[]>([])
  const [writingAll, setWritingAll] = useState(false)
  const refresh = useRefreshTasks()
  const lastId = useRef(0)
  // файлы обрабатываются по одному: два запроса по одной организации мешали бы друг другу
  const queue = useRef(Promise.resolve())
  const enqueue = (job: () => Promise<void>) => (queue.current = queue.current.then(job))

  const update = (id: number, patch: Partial<Item>) =>
    setItems((before) => before.map((item) => (item.id === id ? { ...item, ...patch } : item)))

  const read = async ({ id, file }: Item) => {
    try {
      const data = await api<Declaration>('/declarations/preview', {
        method: 'POST',
        file,
      })
      update(id, { status: 'ready', data })
    } catch (error) {
      update(id, { status: 'failed', error: error as Error })
    }
  }

  const write = async ({ id, file }: Item) => {
    try {
      const data = await api<Declaration>('/declarations/apply', {
        method: 'POST',
        file,
      })
      update(id, { status: 'done', data, error: undefined })
      refresh()
    } catch (error) {
      // предпросмотр остаётся: запись можно повторить
      update(id, { status: 'ready', error: error as Error })
    }
  }

  const add = (chosen: File[]) => {
    const key = (file: File) => `${file.name} ${file.size} ${file.lastModified}`
    // неудачный файл можно выбрать ещё раз, например после добавления организации
    const present = new Set(
      items.filter((item) => item.status !== 'failed').map((item) => key(item.file)),
    )
    const added: Item[] = chosen
      .filter((file) => !present.has(key(file)))
      .map((file) => ({ id: ++lastId.current, file, status: 'reading' }))
    const replaced = new Set(added.map((item) => key(item.file)))
    // новые сверху
    setItems((before) => [...added, ...before.filter((item) => !replaced.has(key(item.file)))])
    for (const item of added) void enqueue(() => read(item))
  }

  const writeOne = (item: Item) => {
    update(item.id, { status: 'writing', error: undefined })
    return enqueue(() => write(item))
  }

  const ready = items.filter(
    (item) => item.status === 'ready' && item.data && changesOf(item.data).length > 0,
  )
  const together = ready.filter((item) => !blockedReason(item, items))
  const reading = items.some((item) => item.status === 'reading')

  const writeAll = async () => {
    setWritingAll(true)
    // корректировки записываются после исходных деклараций
    const ordered = [...together].sort(
      (a, b) => a.data!.correction - b.data!.correction || a.id - b.id,
    )
    await Promise.all(ordered.map(writeOne))
    setWritingAll(false)
  }

  const count = (status: Status) => items.filter((item) => item.status === status).length

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Декларации</h1>
      <p className="text-sm">
        Загрузите XML из учётной программы: декларацию по НДС, прибыли или УСН либо уведомление об
        авансах (УСН, НДФЛ ИП, имущество, транспорт, земля). Можно сразу много файлов по разным
        организациям: сервис найдёт каждую по ИНН и впишет суммы в платежи. Сначала вы увидите, что
        изменится. НДС и ежемесячные авансы по прибыли делятся на три равных платежа с округлением
        до рубля вверх.
      </p>
      <FileDrop
        title="Перетащите XML сюда или нажмите, чтобы выбрать"
        hint="Декларации (основные файлы) и уведомления, сразу несколько. Файлы не сохраняются."
        accept=".xml,text/xml,application/xml"
        onFiles={add}
      />
      {items.length > 1 && (
        <Card title={`Файлов: ${items.length}`}>
          <p className="text-sm" role="status">
            {reading && `Читаем: ${count('reading')}. `}
            Готовы к записи: {ready.length}. Записано: {count('done')}. С ошибкой: {count('failed')}
            .
          </p>
          {count('failed') > 0 && (
            <ul className="text-sm text-red-700 dark:text-red-300">
              {items
                .filter((item) => item.status === 'failed')
                .map((item) => (
                  <li key={item.id} className="break-all">
                    {item.file.name}: {item.error?.message}
                  </li>
                ))}
            </ul>
          )}
          {ready.length > together.length && (
            <Alert kind="warning">
              Не войдут в общую запись: {ready.length - together.length}. Причина указана в карточке
              файла.
            </Alert>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={reading || writingAll || together.length === 0}
              onClick={() => void writeAll()}
            >
              Вписать суммы из всех файлов ({together.length})
            </Button>
            <Button
              variant="secondary"
              disabled={reading || writingAll || count('writing') > 0}
              onClick={() => setItems([])}
            >
              Очистить список
            </Button>
          </div>
        </Card>
      )}
      {items.map((item) => (
        <Loaded
          key={item.id}
          item={item}
          single={items.length === 1}
          blocked={blockedReason(item, items)}
          onWrite={() => void writeOne(item)}
        />
      ))}
    </div>
  )
}

function Loaded({
  item,
  single,
  blocked,
  onWrite,
}: {
  item: Item
  single: boolean
  blocked: string
  onWrite: () => void
}) {
  const { file, data } = item
  if (!data) {
    return (
      <Card title={file.name}>
        {item.status === 'reading' ? <p className="text-sm">Читаем файл…</p> : null}
        <ErrorText error={item.error ?? null} />
      </Card>
    )
  }

  const changes = changesOf(data)
  const done = item.status === 'done'
  return (
    <Card title={data.company_name}>
      <p className="text-sm">
        {data.title}
        {data.correction > 0 && `, корректировка № ${data.correction}`} · ИНН {data.inn}
        <span className="block break-all text-slate-500 dark:text-slate-400">{file.name}</span>
      </p>
      <dl className="text-sm">
        {data.totals.map((total) => (
          <div key={total.label} className="flex flex-wrap justify-between gap-x-3">
            <dt>{total.label}</dt>
            <dd className="font-semibold tabular-nums">{formatKopecks(total.kopecks)}</dd>
          </div>
        ))}
      </dl>
      {data.switches_to_monthly && (
        <Alert kind="warning">
          {done
            ? 'Организация переведена на «Ежемесячно по прибыли прошлого квартала». Появились помесячные платежи, в том числе за прошедшие месяцы: отметьте уже оплаченные.'
            : 'В декларации есть ежемесячные авансы, а в карточке организации стоит «Поквартально». При записи порядок изменится на «Ежемесячно по прибыли прошлого квартала», появятся помесячные платежи, в том числе за прошедшие месяцы года.'}
        </Alert>
      )}
      {data.enables.length > 0 && (
        <Alert kind="warning">
          {done
            ? 'В карточке организации отмечено'
            : 'При записи в карточке организации будет отмечено'}
          : {data.enables.map((name) => `«${name}»`).join(', ')}.{' '}
          {done
            ? 'Появились задачи по этим налогам, в том числе за прошедшие периоды: проверьте их.'
            : 'Появятся задачи по этим налогам, в том числе за прошедшие периоды.'}
        </Alert>
      )}
      {data.warnings.map((warning) => (
        <Alert key={warning} kind="warning">
          {warning}
        </Alert>
      ))}
      {blocked && <Alert kind="warning">{blocked}</Alert>}
      {/* в пачке платежи свёрнуты, чтобы файлы помещались на экране */}
      <details open={single}>
        <summary className="cursor-pointer text-sm font-medium">
          Платежи: {data.parts.length}, меняется: {changes.length}
        </summary>
        <ul className="divide-y divide-slate-200 text-sm dark:divide-slate-700">
          {data.parts.map((part) => (
            <li key={`${part.title} ${part.due_date}`} className="py-2">
              {part.task_id === null ? (
                <span className="font-medium">{part.title} (новый)</span>
              ) : (
                <Link to={`/tasks/${part.task_id}`} className="font-medium text-blue-600 underline">
                  {part.title}
                </Link>
              )}
              <span className="block text-slate-500 dark:text-slate-400">
                срок {formatDate(part.due_date)}
              </span>
              <span className="block tabular-nums">
                {part.kept ? (
                  <span className="text-amber-700 dark:text-amber-300">
                    Не меняется: {part.kept}
                    {part.current_kopecks != null && ` (${formatKopecks(part.current_kopecks)})`}
                  </span>
                ) : (
                  <>
                    {part.current_kopecks != null &&
                      part.current_kopecks !== part.new_kopecks &&
                      `${formatKopecks(part.current_kopecks)} → `}
                    {formatKopecks(part.new_kopecks)}
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      </details>
      <ErrorText error={item.error ?? null} />
      {done ? (
        <Alert kind="success">Суммы записаны. Платежей изменено: {changes.length}.</Alert>
      ) : changes.length === 0 ? (
        <Alert kind="info">Менять нечего.</Alert>
      ) : (
        <Button disabled={item.status === 'writing'} onClick={onWrite}>
          Вписать суммы
        </Button>
      )}
    </Card>
  )
}
