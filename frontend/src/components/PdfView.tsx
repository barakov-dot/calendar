// legacy-сборка работает и в старых встроенных браузерах телефонов
import { getDocument, PDFWorker } from 'pdfjs-dist/legacy/build/pdf.mjs'
import PdfWorker from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?worker'
import { useEffect, useRef, useState } from 'react'

import { Alert } from './ui'

/** Больше страниц у платёжного документа не бывает, а память телефона не бесконечна. */
const MAX_PAGES = 20

/**
 * Страницы PDF рисуются на canvas: встроенного просмотра PDF нет ни в Telegram,
 * ни в мобильных браузерах.
 */
export default function PdfView({ file }: { file: Blob }) {
  const holder = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<{ loading: boolean; error?: boolean; hidden?: number }>({
    loading: true,
  })

  useEffect(() => {
    let cancelled = false
    const box = holder.current!
    // свой поток на каждый просмотр: закрытие одного не мешает другому
    const render = async () => {
      const data = new Uint8Array(await file.arrayBuffer())
      if (cancelled) return
      const port = new PdfWorker()
      const worker = PDFWorker.create({ port })
      const task = getDocument({ data, worker })
      try {
        const pdf = await task.promise
        const width = box.clientWidth || 800
        const sharpness = Math.min(window.devicePixelRatio || 1, 2)
        for (let number = 1; number <= Math.min(pdf.numPages, MAX_PAGES); number++) {
          const page = await pdf.getPage(number)
          if (cancelled) return
          const scale = (width / page.getViewport({ scale: 1 }).width) * sharpness
          const viewport = page.getViewport({ scale })
          const canvas = document.createElement('canvas')
          canvas.width = viewport.width
          canvas.height = viewport.height
          canvas.className = 'w-full bg-white shadow'
          canvas.setAttribute('aria-label', `Страница ${number}`)
          await page.render({ canvas, viewport }).promise
          if (cancelled) return
          box.append(canvas)
          // первая страница уже видна, остальные дорисовываются ниже
          setState({ loading: false })
        }
        setState({ loading: false, hidden: Math.max(0, pdf.numPages - MAX_PAGES) })
      } finally {
        await task.destroy()
        worker.destroy()
        port.terminate()
      }
    }

    render().catch(() => {
      if (!cancelled) setState({ loading: false, error: true })
    })
    return () => {
      cancelled = true
      box.replaceChildren()
    }
  }, [file])

  return (
    <div className="mx-auto w-full max-w-4xl space-y-3">
      {state.loading && <p className="text-center text-sm text-white">Открываем…</p>}
      {state.error && <Alert kind="error">Не удалось показать этот PDF. Скачайте файл.</Alert>}
      <div ref={holder} className="space-y-3" />
      {!!state.hidden && <Alert>Ещё страниц: {state.hidden}. Скачайте файл целиком.</Alert>}
    </div>
  )
}
