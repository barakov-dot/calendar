import type { Role } from './types'

export const ROLE_NAMES: Record<Role, string> = {
  admin: 'администратор',
  chief: 'главный бухгалтер',
  accountant: 'бухгалтер',
  assistant: 'помощник бухгалтера',
  client: 'клиент',
}

/** Кто вправе менять данные компаний и задач. Помощник только смотрит.
 *  Это лишь для интерфейса: права проверяет сервер. */
export const canEdit = (role: Role) => isManager(role) || role === 'accountant'

/** Руководит работой: все компании, пользователи, приглашения, замещения. */
export const isManager = (role: Role) => role === 'admin' || role === 'chief'
