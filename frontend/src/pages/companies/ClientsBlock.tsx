import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'

import InviteList from '../../components/InviteList'
import { Badge, Button, Card, Checkbox, ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import { fullName } from '../../lib/format'
import { canEdit, isManager } from '../../lib/roles'
import type { Company, Invite, Member, User } from '../../lib/types'

export default function ClientsBlock({ company, user }: { company: Company; user: User }) {
  const editable = canEdit(user.role)
  // приглашает только администратор
  const canInvite = isManager(user.role)
  const base = `/companies/${company.id}`
  const queryClient = useQueryClient()
  const [paysSelf, setPaysSelf] = useState(false)
  const invites = useQuery({
    queryKey: ['client-invites', company.id],
    queryFn: () => api<Invite[]>(`${base}/invites`),
    refetchOnMount: 'always',
    enabled: canInvite,
  })
  const reload = () => {
    void queryClient.invalidateQueries({ queryKey: ['company', company.id] })
    void queryClient.invalidateQueries({ queryKey: ['client-invites', company.id] })
    void queryClient.invalidateQueries({ queryKey: ['companies'] })
  }
  const update = useMutation({
    mutationFn: ({ member, patch }: { member: Member; patch: Partial<Member> }) =>
      api(`${base}/members/${member.user_id}`, { method: 'PATCH', body: patch }),
    onSettled: reload,
  })
  const unlink = useMutation({
    mutationFn: (userId: number) => api(`${base}/members/${userId}`, { method: 'DELETE' }),
    onSettled: reload,
  })
  const invite = useMutation({
    mutationFn: () =>
      api<Invite>(`${base}/invites`, { method: 'POST', body: { can_mark_paid: paysSelf } }),
    onSuccess: () => {
      setPaysSelf(false)
      reload()
    },
  })
  const revoke = useMutation({
    mutationFn: (id: number) => api(`${base}/invites/${id}`, { method: 'DELETE' }),
    onSettled: reload,
  })

  return (
    <Card title="Клиенты">
      <ErrorText error={update.error ?? unlink.error} />
      {company.members.length === 0 && <p className="text-sm">В боте пока никого нет.</p>}
      <ul className="divide-y divide-slate-200 dark:divide-slate-700">
        {company.members.map((member) => (
          <li key={member.user_id} className="space-y-2 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span>
                {canInvite ? (
                  <Link
                    to={`/users/${member.user_id}`}
                    className="text-blue-700 underline dark:text-blue-300"
                  >
                    {fullName(member)}
                  </Link>
                ) : (
                  fullName(member)
                )}{' '}
                {member.bot_blocked && <Badge kind="warning">заблокировал бота</Badge>}
              </span>
              {editable && (
                <Button
                  variant="danger"
                  onClick={() => {
                    if (window.confirm(`Отвязать клиента ${fullName(member)}?`)) {
                      unlink.mutate(member.user_id)
                    }
                  }}
                >
                  Отвязать
                </Button>
              )}
            </div>
            <Checkbox
              label="Клиент платит сам"
              checked={member.can_mark_paid}
              disabled={!editable || update.isPending}
              onChange={(can_mark_paid) => update.mutate({ member, patch: { can_mark_paid } })}
            />
            <Checkbox
              label="Получает напоминания"
              checked={member.receive_reminders}
              disabled={!editable || update.isPending}
              onChange={(receive_reminders) =>
                update.mutate({ member, patch: { receive_reminders } })
              }
            />
          </li>
        ))}
      </ul>
      {editable && !canInvite && (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Приглашения клиентам выдаёт администратор.
        </p>
      )}
      {canInvite && !company.is_archived && (
        <>
          <Checkbox
            label="Клиент платит сам (сможет отмечать оплату)"
            checked={paysSelf}
            onChange={setPaysSelf}
          />
          <Button disabled={invite.isPending} onClick={() => invite.mutate()}>
            Пригласить клиента
          </Button>
        </>
      )}
      <ErrorText error={invite.error ?? invites.error ?? revoke.error} />
      <InviteList invites={invites.data ?? []} onRevoke={(id) => revoke.mutate(id)} />
    </Card>
  )
}
