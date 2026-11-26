import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'

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
      />
      {hint && <span className="mt-1 block text-slate-500 dark:text-slate-400">{hint}</span>}
    </label>
  )
}

export function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        className="size-4"
        checked={checked}
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
    <section className="space-y-4 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
      {title && <h2 className="text-lg font-semibold">{title}</h2>}
      {children}
    </section>
  )
}

export function ErrorText({ error }: { error: Error | null }) {
  return error ? <Alert kind="error">{error.message}</Alert> : null
}
