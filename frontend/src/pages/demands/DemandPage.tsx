import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'

import FileDrop from '../../components/FileDrop'
import FilePreview from '../../components/FilePreview'
import { Alert, Button, Card, ErrorText } from '../../components/ui'
import { api, apiFile } from '../../lib/api'
import { formatDate, formatKopecks, toRublesText } from '../../lib/company'
import type { Demand, DemandStep } from '../../lib/demands'
import { saveBlob } from '../../lib/files'
import { canEdit } from '../../lib/roles'
import { relativeDay, STATUS_NAMES, todayIso } from '../../lib/tasks'
import { miniAppInitData } from '../../lib/telegram'
import type { User } from '../../lib/types'
import { useBulkStatus, useRefreshTasks } from '../../lib/useTasks'
import DemandForm, { type DemandBody } from './DemandForm'

function useRefreshDemand() {
  const queryClient = useQueryClient()
  const refresh = useRefreshTasks()
  return () => {
    refresh()
    for (const key of ['demands', 'demand']) {
      void queryClient.invalidateQueries({ queryKey: [key] })
    }
  }
}

export default function DemandPage({ user }: { user: User }) {
  const id = Number(useParams().id)
  const demand = useQuery({
    queryKey: ['demand', id],
    queryFn: () => api<Demand>(`/demands/${id}`),
    refetchOnMount: 'always',
  })
  return (
    <div className="space-y-4">
      <Link to="/demands" className="text-sm text-blue-600 underline">
        ← Все требования
      </Link>
      <ErrorText error={demand.error} />
      {demand.data && (
        <Loaded
          key={id}
          demand={demand.data}
          editable={canEdit(user.role)}
          client={user.role === 'client'}
        />
      )}
    </div>
  )
}

function Loaded({
  demand,
  editable,
  client,
}: {
  demand: Demand
  editable: boolean
  client: boolean
}) {
  const refresh = useRefreshDemand()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [editing, setEditing] = useState(false)
  const remove = useMutation({
    mutationFn: () => api(`/demands/${demand.id}`, { method: 'DELETE' }),
    onSuccess: async () => {
      await navigate('/demands', { replace: true })
      refresh()
    },
  })

  if (editing) {
    return (
      <DemandForm
        initial={{
          company_id: demand.company_id,
          knd: demand.knd,
          number: demand.number,
          doc_date: demand.doc_date,
          sent_date: demand.sent_date === demand.doc_date ? '' : demand.sent_date,
          // посчитанные даты оставляем пустыми, чтобы они пересчитывались
          receipt_date: demand.receipt_set ? demand.receipt_date : '',
          response_workdays: demand.response_workdays ? String(demand.response_workdays) : '',
          response_date: demand.response_set ? demand.response_date : '',
          amount: toRublesText(demand.amount_kopecks),
          note: demand.note,
        }}
        isNew={false}
        submitLabel="Сохранить"
        onCancel={() => setEditing(false)}
        onSubmit={async (body: DemandBody) => {
          await api(`/demands/${demand.id}`, { method: 'PUT', body })
          refresh()
          setEditing(false)
        }}
      />
    )
  }

  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      <div className="min-w-0 space-y-4">
        {params.get('file') === 'failed' && !demand.filename && (
          <Alert kind="error">Требование сохранено, но файл не загрузился. Приложите его.</Alert>
        )}
        <Card title={`${demand.name}${demand.number ? ` № ${demand.number}` : ''}`}>
          <p className="text-sm">
            {client ? (
              demand.company_name
            ) : (
              <Link to={`/companies/${demand.company_id}`} className="text-blue-600 underline">
                {demand.company_name}
              </Link>
            )}
            {demand.knd && ` · КНД ${demand.knd}`}
          </p>
          <p className="text-sm">
            Документ от {formatDate(demand.doc_date)}
            {demand.sent_date !== demand.doc_date && `, отправлен ${formatDate(demand.sent_date)}`}
          </p>
          {demand.amount_kopecks != null && (
            <p className="text-lg font-semibold">{formatKopecks(demand.amount_kopecks)}</p>
          )}
          {demand.note && <p className="text-sm break-words">{demand.note}</p>}
        </Card>
        <Card title="Сроки">
          <Step
            title="Подписать квитанцию о приёме"
            step={demand.receipt}
            done="done"
            doneLabel="Квитанция подписана"
            editable={editable}
          />
          <Step
            title={demand.action}
            step={demand.response}
            done={demand.knd === '1160001' ? 'paid' : 'done'}
            doneLabel={demand.knd === '1160001' ? 'Уплачено' : 'Выполнено'}
            editable={editable}
          />
        </Card>
      </div>
      <div className="min-w-0 space-y-4">
        <DocumentFile demand={demand} editable={editable} />
        {editable && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setEditing(true)}>
              Изменить
            </Button>
            <Button
              variant="danger"
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm('Удалить требование вместе с его сроками и файлом?')) {
                  remove.mutate()
                }
              }}
            >
              Удалить
            </Button>
          </div>
        )}
        <ErrorText error={remove.error} />
      </div>
    </div>
  )
}

function Step({
  title,
  step,
  done,
  doneLabel,
  editable,
}: {
  title: string
  step: DemandStep | null
  done: 'done' | 'paid'
  doneLabel: string
  editable: boolean
}) {
  const today = todayIso()
  const refresh = useRefreshDemand()
  const change = useBulkStatus(refresh)
  if (!step) return null
  const open = step.status === 'planned'
  const overdue = open && step.due_date < today
  return (
    <section aria-label={title} className="space-y-1 text-sm">
      {step.task_id === null ? (
        <span className="font-medium">{title}</span>
      ) : (
        <Link to={`/tasks/${step.task_id}`} className="font-medium text-blue-600 underline">
          {title}
        </Link>
      )}
      <p className={overdue ? 'font-semibold text-red-700 dark:text-red-400' : ''}>
        {formatDate(step.due_date)}
        {open ? ` · ${relativeDay(step.due_date, today)}` : ` · ${STATUS_NAMES[step.status]} ✓`}
      </p>
      {editable && step.task_id !== null && (
        <Button
          variant={open ? 'primary' : 'secondary'}
          disabled={change.isPending}
          onClick={() =>
            change.mutate({ ids: [step.task_id!], status: open ? done : 'planned' })
          }
        >
          {open ? doneLabel : 'Вернуть в план'}
        </Button>
      )}
      <ErrorText error={change.error} />
    </section>
  )
}

function DocumentFile({ demand, editable }: { demand: Demand; editable: boolean }) {
  const [inTelegram] = useState(() => miniAppInitData() !== null)
  const refresh = useRefreshDemand()
  const [opened, setOpened] = useState(false)
  const close = useCallback(() => setOpened(false), [])
  const path = `/demands/${demand.id}/file`
  const upload = useMutation({
    mutationFn: (file: File) => api(path, { method: 'POST', file }),
    onSuccess: refresh,
  })
  const download = useMutation({
    mutationFn: async () => saveBlob(await apiFile(path), demand.filename),
  })
  const send = useMutation({ mutationFn: () => api(`${path}/send`, { method: 'POST' }) })

  if (!demand.filename && !editable) return null
  return (
    <Card title="Документ">
      {demand.filename && (
        <>
          <p className="text-sm break-all">{demand.filename}</p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setOpened(true)}>Открыть</Button>
            {/* внутри Telegram скачивание из окна не работает */}
            {!inTelegram && (
              <Button variant="secondary" onClick={() => download.mutate()}>
                Скачать
              </Button>
            )}
            <Button variant="secondary" disabled={send.isPending} onClick={() => send.mutate()}>
              Прислать в Telegram
            </Button>
          </div>
        </>
      )}
      {send.isSuccess && <Alert kind="success">Файл отправлен вам в чат с ботом.</Alert>}
      {editable && (
        <FileDrop
          title={demand.filename ? 'Заменить файл' : 'Приложить файл'}
          hint="PDF или фото, до 10 МБ"
          accept=".pdf,image/*"
          disabled={upload.isPending}
          onFiles={([file]) => upload.mutate(file)}
        />
      )}
      <ErrorText error={upload.error ?? download.error ?? send.error} />
      {opened && (
        <FilePreview
          file={{
            id: demand.id,
            filename: demand.filename,
            content_type: demand.content_type,
            path,
          }}
          onClose={close}
        />
      )}
    </Card>
  )
}
