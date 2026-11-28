import { Checkbox, ErrorText } from '../../components/ui'
import type { StaffRef } from '../../lib/types'
import { useStaff } from './useStaff'

export interface StaffChoice {
  accountant_ids: number[]
  assistant_ids: number[]
}

/** Выбор бухгалтеров и помощников организации (для администратора и главного бухгалтера). */
export function StaffPicker({
  value,
  onChange,
  current = { accountants: [], assistants: [] },
}: {
  value: StaffChoice
  onChange: (value: StaffChoice) => void
  /** Уже назначенные: среди них могут быть отключённые, которых нет в общем списке. */
  current?: { accountants: StaffRef[]; assistants: StaffRef[] }
}) {
  const staff = useStaff(true)

  const group = (
    title: string,
    key: keyof StaffChoice,
    assigned: StaffRef[],
    assistants: boolean,
  ) => {
    const active = (staff.data ?? []).filter(
      (member) => (member.role === 'assistant') === assistants,
    )
    const disabled = staff.data
      ? assigned.filter((member) => !active.some((other) => other.id === member.id))
      : []
    const options = [
      ...active,
      ...disabled.map((member) => ({ id: member.id, name: `${member.name} (отключён)` })),
    ]
    return (
      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-medium">{title}</legend>
        {staff.data && options.length === 0 && (
          <p className="text-sm text-slate-500 dark:text-slate-400">Пока некого назначить.</p>
        )}
        {options.map((member) => (
          <Checkbox
            key={member.id}
            label={member.name}
            checked={value[key].includes(member.id)}
            onChange={(checked) =>
              onChange({
                ...value,
                [key]: checked
                  ? [...value[key], member.id]
                  : value[key].filter((id) => id !== member.id),
              })
            }
          />
        ))}
      </fieldset>
    )
  }

  return (
    <>
      <ErrorText error={staff.error} />
      <div className="grid items-start gap-4 sm:grid-cols-2">
        {group('Бухгалтеры', 'accountant_ids', current.accountants, false)}
        {group('Помощники', 'assistant_ids', current.assistants, true)}
      </div>
      {value.accountant_ids.length === 0 && (
        <p className="text-sm text-amber-700 dark:text-amber-400">
          Отметьте хотя бы одного бухгалтера.
        </p>
      )}
    </>
  )
}
