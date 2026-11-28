import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from 'react'

const buttonStyles = {
  primary: 'bg-blue-600 text-white hover:bg-blue-700',
  secondary:
    'border border-slate-300 hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800',
  danger: 'border border-red-300 text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950',
}

export function Button({
  variant = 'primary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof buttonStyles }) {
  return (
    <button
      type="button"
      className={`rounded-lg px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${buttonStyles[variant]} ${className}`}
      {...props}
    />
  )
}

/** Календарь по нажатию на всё поле, а не только на значок. */
function openPicker(input: HTMLInputElement) {
  try {
    if (!input.disabled && !input.readOnly) input.showPicker?.()
  } catch {
    // браузер открывает календарь сам или не умеет по запросу
  }
}

export function Field({
  label,
  hint,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      <input
        className="w-full rounded-lg border border-slate-300 bg-transparent px-3 py-2 dark:border-slate-600"
        {...props}
        onClick={(event) => {
          props.onClick?.(event)
          if (props.type === 'date') openPicker(event.currentTarget)
        }}
      />
      {hint && <span className="mt-1 block text-slate-500 dark:text-slate-400">{hint}</span>}
    </label>
  )
}

export function Select({
  label,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      <select
        className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-900"
        {...props}
      >
        {children}
      </select>
    </label>
  )
}

export function Badge({
  kind = 'info',
  children,
}: {
  kind?: 'info' | 'warning'
  children: ReactNode
}) {
  const style =
    kind === 'warning'
      ? 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200'
      : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'
  return <span className={`rounded-full px-2 py-0.5 text-xs ${style}`}>{children}</span>
}

export function Checkbox({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        className="size-4"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  )
}

const alertStyles = {
  info: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200',
  success: 'bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-200',
  error: 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200',
  warning: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
}

export function Alert({
  kind = 'info',
  children,
}: {
  kind?: keyof typeof alertStyles
  children: ReactNode
}) {
  return (
    <div
      role={kind === 'error' ? 'alert' : 'status'}
      className={`rounded-lg px-3 py-2 text-sm break-words ${alertStyles[kind]}`}
    >
      {children}
    </div>
  )
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="min-w-0 space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-xs dark:border-slate-800 dark:bg-slate-900">
      {title && <h2 className="text-base font-semibold">{title}</h2>}
      {children}
    </section>
  )
}

/** Вкладки внутри страницы. */
export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: [T, string][]
  active: T
  onChange: (tab: T) => void
}) {
  return (
    <div
      role="tablist"
      className="flex flex-wrap gap-x-1 border-b border-slate-200 dark:border-slate-800"
    >
      {tabs.map(([key, title]) => (
        <button
          key={key}
          type="button"
          role="tab"
          aria-selected={key === active}
          onClick={() => onChange(key)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm whitespace-nowrap ${
            key === active
              ? 'border-blue-600 font-medium text-blue-700 dark:text-blue-300'
              : 'border-transparent text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100'
          }`}
        >
          {title}
        </button>
      ))}
    </div>
  )
}

export function ErrorText({ error }: { error: Error | null }) {
  return error ? <Alert kind="error">{error.message}</Alert> : null
}
