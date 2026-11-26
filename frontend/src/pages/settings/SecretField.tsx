import { Button, Field } from '../../components/ui'

/** Секрет не приходит с сервера: пустое поле означает «не менять». */
export default function SecretField({
  label,
  value,
  saved,
  onChange,
  onClear,
}: {
  label: string
  value: string
  saved: boolean
  onChange: (value: string) => void
  onClear: () => void
}) {
  return (
    <div className="space-y-2">
      <Field
        label={label}
        type="password"
        autoComplete="new-password"
        value={value}
        placeholder={saved ? '•••• сохранён' : ''}
        hint={saved ? 'Оставьте пустым, чтобы не менять' : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
      {saved && (
        <Button
          variant="danger"
          onClick={() => {
            if (window.confirm(`Удалить сохранённое значение «${label}»?`)) onClear()
          }}
        >
          Очистить: {label}
        </Button>
      )}
    </div>
  )
}
