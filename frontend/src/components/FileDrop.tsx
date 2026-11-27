import { useState, type DragEvent } from 'react'

/** Окно для файлов: перетащить мышью или нажать и выбрать. */
export default function FileDrop({
  title,
  hint,
  accept,
  disabled,
  onFiles,
}: {
  title: string
  hint: string
  accept: string
  disabled?: boolean
  onFiles: (files: File[]) => void
}) {
  const [over, setOver] = useState(false)

  const give = (list: FileList | null) => {
    const files = Array.from(list ?? [])
    if (!disabled && files.length) onFiles(files)
  }
  const hold = (event: DragEvent) => {
    // без этого браузер откроет брошенный файл вместо страницы
    event.preventDefault()
    setOver(true)
  }

  return (
    <label
      onDragEnter={hold}
      onDragOver={hold}
      onDragLeave={(event) => {
        // переход между вложенными элементами — не уход из окна
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(false)
      }}
      onDrop={(event) => {
        event.preventDefault()
        setOver(false)
        give(event.dataTransfer.files)
      }}
      className={`flex min-h-32 cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed p-4 text-center text-sm focus-within:border-blue-600 ${
        over
          ? 'border-blue-600 bg-blue-50 dark:bg-blue-950'
          : 'border-slate-300 hover:border-blue-400 dark:border-slate-600'
      } ${disabled ? 'cursor-wait opacity-60' : ''}`}
    >
      <span className="font-medium">{over ? 'Отпустите файл здесь' : title}</span>
      <span className="text-slate-500 dark:text-slate-400">{hint}</span>
      <input
        type="file"
        multiple
        accept={accept}
        disabled={disabled}
        className="sr-only"
        aria-label={title}
        onChange={(event) => {
          give(event.target.files)
          event.target.value = ''
        }}
      />
    </label>
  )
}
