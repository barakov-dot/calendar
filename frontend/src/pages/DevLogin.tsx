import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'

import { Button, Card, ErrorText } from '../components/ui'
import { api, session, type Tokens } from '../lib/api'
import { fullName } from '../lib/format'
import type { User } from '../lib/types'

export default function DevLogin() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const users = useQuery({ queryKey: ['dev-users'], queryFn: () => api<User[]>('/auth/dev-users') })
  const login = useMutation({
    mutationFn: (userId: number) =>
      api<Tokens>('/auth/dev-login', { method: 'POST', body: { user_id: userId } }),
    onSuccess: (tokens) => {
      queryClient.clear()
      session.set(tokens)
      navigate('/')
    },
  })

  return (
    <main className="mx-auto max-w-md p-4">
      <Card title="Вход для разработки">
        <ErrorText error={users.error ?? login.error} />
        {users.data?.length === 0 && (
          <p className="text-sm">Пользователей нет. Выполните make seed-dev.</p>
        )}
        {users.data?.map((user) => (
          <Button
            key={user.id}
            variant="secondary"
            className="block w-full text-left"
            disabled={!user.is_active}
            onClick={() => login.mutate(user.id)}
          >
            {fullName(user)} — {user.role}
          </Button>
        ))}
      </Card>
    </main>
  )
}
