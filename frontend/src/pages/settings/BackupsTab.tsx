import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Alert, Button, Card, ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type { Backup, SettingsResponse } from '../../lib/types'
import { SETTINGS_KEY } from './useSettings'

export default function BackupsTab() {
  const queryClient = useQueryClient()
  const backups = useQuery({
    queryKey: ['backups'],
    queryFn: () => api<Backup[]>('/admin/settings/backups'),
    refetchOnMount: 'always',
  })
  const restore = useMutation({
    mutationFn: (name: string) =>
      api<SettingsResponse>(`/admin/settings/backups/${encodeURIComponent(name)}/restore`, {
        method: 'POST',
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(SETTINGS_KEY, data)
      void queryClient.invalidateQueries({ queryKey: ['backups'] })
    },
  })

  return (
    <Card title="Резервные копии настроек">
      <p className="text-sm">
        Копия делается перед каждым сохранением, хранятся 20 последних. Восстановление
        возвращает все настройки, включая ключи и пароли.
      </p>
      <ErrorText error={backups.error ?? restore.error} />
      {restore.isSuccess && <Alert kind="success">Настройки восстановлены.</Alert>}
      {backups.data?.length === 0 && <p className="text-sm">Копий пока нет.</p>}
      <ul className="divide-y divide-slate-200 dark:divide-slate-700">
        {backups.data?.map((backup) => {
          const title = backup.created_at ? formatDateTime(backup.created_at) : backup.name
          return (
            <li key={backup.name} className="flex items-center justify-between gap-2 py-2 text-sm">
              <span>
                {title}
                {!backup.valid && <span className="text-red-600"> — повреждена</span>}
              </span>
              <Button
                variant="secondary"
                disabled={!backup.valid || restore.isPending}
                onClick={() => {
                  if (window.confirm(`Восстановить настройки от ${title}?`)) {
                    restore.mutate(backup.name)
                  }
                }}
              >
                Восстановить
              </Button>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
