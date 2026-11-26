import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Button, Card, ErrorText } from '../components/ui'
import { api } from '../lib/api'
import { formatDateTime, fullName } from '../lib/format'
import type { Invite, User } from '../lib/types'

export default function Accountants() {
  const queryClient = useQueryClient()
  const accountants = useQuery({
    queryKey: ['accountants'],
    queryFn: () => api<User[]>('/admin/accountants'),
  })
  const invites = useQuery({
    queryKey: ['invites'],
    queryFn: () => api<Invite[]>('/admin/invites'),
  })
  const reload = () => queryClient.invalidateQueries()

  const invite = useMutation({
    mutationFn: () =>
      api<Invite>('/admin/invites', { method: 'POST', body: { kind: 'accountant' } }),
    onSuccess: reload,
  })
  const revoke = useMutation({
    mutationFn: (id: number) => api(`/admin/invites/${id}`, { method: 'DELETE' }),
    onSettled: reload,
  })
  const toggle = useMutation({
    mutationFn: (user: User) =>
      api(`/admin/accountants/${user.id}`, {
        method: 'PATCH',
        body: { is_active: !user.is_active },
      }),
    onSuccess: reload,
  })

  return (
    <div className="space-y-4">
      <Card title="Бухгалтеры">
        <ErrorText error={accountants.error ?? toggle.error} />
        {accountants.data?.length === 0 && <p className="text-sm">Пока никого нет.</p>}
        <ul className="divide-y divide-slate-200 dark:divide-slate-700">
          {accountants.data?.map((user) => (
            <li key={user.id} className="flex items-center justify-between gap-2 py-2">
              <span>
                {fullName(user)}
                {user.username && (
                  <span className="text-slate-500 dark:text-slate-400"> @{user.username}</span>
                )}
                {!user.is_active && <span className="text-red-600"> — отключён</span>}
              </span>
              <Button
                variant={user.is_active ? 'danger' : 'secondary'}
                disabled={toggle.isPending}
                onClick={() => {
                  if (!user.is_active || window.confirm(`Отключить доступ: ${fullName(user)}?`)) {
                    toggle.mutate(user)
                  }
                }}
              >
                {user.is_active ? 'Отключить' : 'Включить'}
              </Button>
            </li>
          ))}
        </ul>
      </Card>

      <Card title="Приглашения">
        <p className="text-sm">Ссылка одноразовая и действует 7 дней.</p>
        <Button onClick={() => invite.mutate()} disabled={invite.isPending}>
          Пригласить бухгалтера
        </Button>
        <ErrorText error={invite.error ?? invites.error ?? revoke.error} />
        <ul className="space-y-3">
          {invites.data?.map((item) => (
            <li key={item.id} className="space-y-2">
              <input
                readOnly
                aria-label="Ссылка-приглашение"
                value={item.link}
                onFocus={(event) => event.target.select()}
                className="w-full rounded-lg border border-slate-300 bg-transparent px-3 py-2 text-sm dark:border-slate-600"
              />
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Button
                  variant="secondary"
                  onClick={() => navigator.clipboard?.writeText(item.link)}
                >
                  Копировать
                </Button>
                <Button variant="danger" onClick={() => revoke.mutate(item.id)}>
                  Отозвать
                </Button>
                <span className="text-slate-500 dark:text-slate-400">
                  до {formatDateTime(item.expires_at)}
                </span>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
