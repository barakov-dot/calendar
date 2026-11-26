export default function TextArea({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      <textarea
        className="w-full rounded-lg border border-slate-300 bg-transparent px-3 py-2 dark:border-slate-600"
        rows={3}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}
