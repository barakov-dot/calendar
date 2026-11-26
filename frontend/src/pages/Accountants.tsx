import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import InviteList from '../components/InviteList'
import { Button, Card, ErrorText } from '../components/ui'
import { api } from '../lib/api'
import { fullName } from '../lib/format'
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
        <InviteList invites={invites.data ?? []} onRevoke={(id) => revoke.mutate(id)} />
      </Card>
    </div>
  )
}
