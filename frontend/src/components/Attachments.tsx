import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'

import { api, apiFile } from '../lib/api'
import { formatSize, saveBlob } from '../lib/files'
import { formatDateTime } from '../lib/format'
import { miniAppInitData } from '../lib/telegram'
import { useRefreshTasks } from '../lib/useTasks'
import FileDrop from './FileDrop'
import FilePreview, { type PreviewFile } from './FilePreview'
import { Alert, Button, Card, ErrorText } from './ui'

export interface AttachmentList {
  items: {
    id: number
    filename: string
    content_type: string
    size: number
    uploaded_by_name: string
    created_at: string
    can_delete: boolean
  }[]
  can_upload: boolean
  max_bytes: number
}

/** Файлы к платежу: платёжка в PDF или фотографией. */
export default function Attachments({ taskId }: { taskId: number }) {
  const [inTelegram] = useState(() => miniAppInitData() !== null)
  const queryClient = useQueryClient()
  const refresh = useRefreshTasks()
  const key = ['attachments', taskId]
  const list = useQuery({
    queryKey: key,
    queryFn: () => api<AttachmentList>(`/tasks/${taskId}/attachments`),
    refetchOnMount: 'always',
  })
  const changed = () => {
    void queryClient.invalidateQueries({ queryKey: key })
    refresh()
  }
  const [opened, setOpened] = useState<PreviewFile | null>(null)
  const closePreview = useCallback(() => setOpened(null), [])
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      // по одному: так сервер проверяет предел числа файлов, а ошибка называет файл
      for (const file of files) {
        if (list.data && file.size > list.data.max_bytes) {
          throw new Error(`Файл больше 10 МБ: ${file.name}`)
        }
        await api(`/tasks/${taskId}/attachments`, { method: 'POST', file })
      }
    },
    onSettled: changed,
  })
  const download = useMutation({
    mutationFn: async ({ id, name }: { id: number; name: string }) =>
      saveBlob(await apiFile(`/attachments/${id}`), name),
  })
  const send = useMutation({
    mutationFn: (id: number) => api(`/attachments/${id}/send`, { method: 'POST' }),
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`/attachments/${id}`, { method: 'DELETE' }),
    onSettled: changed,
  })

  const data = list.data
  if (data && data.items.length === 0 && !data.can_upload) return null

  return (
    <Card title="Платёжка">
      <ErrorText
        error={list.error ?? upload.error ?? download.error ?? send.error ?? remove.error}
      />
      {send.isSuccess && <Alert kind="success">Файл отправлен вам в чат с ботом.</Alert>}
      <ul className="divide-y divide-slate-200 dark:divide-slate-700">
        {data?.items.map((item) => (
          <li key={item.id} className="space-y-2 py-2">
            <button
              type="button"
              onClick={() => setOpened(item)}
              className="block w-full cursor-pointer rounded-lg text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50"
            >
              <span className="block font-medium break-all text-blue-700 underline dark:text-blue-300">
                {item.filename}
              </span>
              <span className="text-slate-500 dark:text-slate-400">
                {formatSize(item.size)} · {item.uploaded_by_name},{' '}
                {formatDateTime(item.created_at)}
              </span>
            </button>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={() => setOpened(item)}>
                Открыть
              </Button>
              {/* внутри Telegram скачивание из окна не работает */}
              {!inTelegram && (
                <Button
                  variant="secondary"
                  onClick={() => download.mutate({ id: item.id, name: item.filename })}
                >
                  Скачать
                </Button>
              )}
              <Button
                variant="secondary"
                disabled={send.isPending}
                onClick={() => send.mutate(item.id)}
              >
                Прислать в Telegram
              </Button>
              {item.can_delete && (
                <Button
                  variant="danger"
                  onClick={() => {
                    if (window.confirm(`Удалить файл «${item.filename}»?`)) remove.mutate(item.id)
                  }}
                >
                  Удалить
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {data?.can_upload && (
        <FileDrop
          title={upload.isPending ? 'Загружаем…' : 'Перетащите файл сюда или нажмите, чтобы выбрать'}
          hint="PDF или фото, до 10 МБ"
          accept="application/pdf,image/*"
          disabled={upload.isPending}
          onFiles={(files) => upload.mutate(files)}
        />
      )}
      {opened && <FilePreview file={opened} onClose={closePreview} />}
    </Card>
  )
}
