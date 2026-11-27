import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'

import { apiFile } from '../lib/api'
import { Alert, Button, ErrorText } from './ui'

// библиотека PDF тяжёлая и загружается только при открытии файла
const PdfView = lazy(() => import('./PdfView'))

export interface PreviewFile {
  id: number
  filename: string
  content_type: string
}

function Picture({ file, name }: { file: Blob; name: string }) {
  const [broken, setBroken] = useState(false)
  // адрес файла живёт, пока картинка на странице
  const attach = useCallback(
    (image: HTMLImageElement) => {
      const url = URL.createObjectURL(file)
      image.src = url
      return () => URL.revokeObjectURL(url)
    },
    [file],
  )

  if (broken) {
    return (
      <Alert kind="warning">
        Этот браузер не показывает такой формат (обычно это фото HEIC с iPhone). Скачайте файл.
      </Alert>
    )
  }
  return (
    <img ref={attach} alt={name} className="mx-auto max-w-full" onError={() => setBroken(true)} />
  )
}

/** Просмотр файла поверх страницы, без скачивания. */
export default function FilePreview({
  file,
  onClose,
}: {
  file: PreviewFile
  onClose: () => void
}) {
  const close = useRef<HTMLDivElement>(null)
  const content = useQuery({
    queryKey: ['attachment-content', file.id],
    queryFn: () => apiFile(`/attachments/${file.id}`),
    // содержимое файла не меняется, но и держать его в памяти после закрытия незачем
    staleTime: Infinity,
    gcTime: 0,
  })

  useEffect(() => {
    const before = document.activeElement as HTMLElement | null
    close.current?.querySelector('button')?.focus()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      before?.focus()
    }
  }, [onClose])

  const data = content.data
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={file.filename}
      className="fixed inset-0 z-50 flex flex-col bg-slate-950/90"
    >
      <div ref={close} className="flex items-center gap-3 bg-white p-3 dark:bg-slate-900">
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{file.filename}</span>
        <Button variant="secondary" onClick={onClose}>
          Закрыть
        </Button>
      </div>
      <div
        className="min-h-0 flex-1 overflow-auto p-3"
        onClick={(event) => event.target === event.currentTarget && onClose()}
      >
        {content.isPending && <p className="text-center text-sm text-white">Загружаем…</p>}
        <ErrorText error={content.error} />
        {data &&
          (file.content_type === 'application/pdf' ? (
            <Suspense fallback={<p className="text-center text-sm text-white">Открываем…</p>}>
              <PdfView file={data} />
            </Suspense>
          ) : (
            <Picture file={data} name={file.filename} />
          ))}
      </div>
    </div>
  )
}
