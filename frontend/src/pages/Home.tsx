import { Card } from '../components/ui'
import type { Role, User } from '../lib/types'

const ROLE_NAMES: Record<Role, string> = {
  admin: 'администратор',
  accountant: 'бухгалтер',
  client: 'клиент',
}

export default function Home({ user }: { user: User }) {
  return (
    <Card title="Платёжный календарь">
      <p>Вы вошли как {ROLE_NAMES[user.role]}.</p>
      <p className="text-slate-500 dark:text-slate-400">
        Компании и календарь сроков появятся в следующих версиях.
      </p>
    </Card>
  )
}
