import { useState } from 'react'

import { Button } from '../../components/ui'
import { formatDate, formatKopecks } from '../../lib/company'
import PatentForm, { type PatentData } from './PatentForm'

/** Список патентов с добавлением и правкой. Где хранить изменения, решает вызывающий. */
export default function PatentList<T extends PatentData>({
  patents,
  onAdd,
  onEdit,
  onRemove,
}: {
  patents: T[]
  onAdd: (patent: PatentData) => void
  onEdit: (index: number, patent: PatentData) => void
  onRemove: (index: number) => void
}) {
  // номер редактируемого патента, 'new' — добавление
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const close = () => setEditing(null)

  return (
    <div className="space-y-2">
      {patents.length === 0 && <p className="text-sm">Патентов нет.</p>}
      {patents.map((patent, index) =>
        editing === index ? (
          <PatentForm
            key={index}
            initial={patent}
            submitLabel="Сохранить патент"
            onCancel={close}
            onSubmit={(data) => {
              onEdit(index, data)
              close()
            }}
          />
        ) : (
          <div key={index} className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span>
              {patent.number ? `№ ${patent.number}, ` : ''}
              {formatDate(patent.date_start)} — {formatDate(patent.date_end)}
              {patent.region && `, ${patent.region}`}
              {patent.cost_kopecks != null && `, ${formatKopecks(patent.cost_kopecks)}`}
            </span>
            <span className="flex gap-2">
              <Button variant="secondary" onClick={() => setEditing(index)}>
                Изменить
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  if (window.confirm('Удалить патент?')) onRemove(index)
                }}
              >
                Удалить
              </Button>
            </span>
          </div>
        ),
      )}
      {editing === 'new' ? (
        <PatentForm
          submitLabel="Добавить"
          onCancel={close}
          onSubmit={(data) => {
            onAdd(data)
            close()
          }}
        />
      ) : (
        <Button variant="secondary" onClick={() => setEditing('new')}>
          Добавить патент
        </Button>
      )}
    </div>
  )
}
