import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'

import FileDrop from '../../components/FileDrop'
import { Button, Card, ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import { refreshSiteIcon, SITE_ICON_URL } from '../../lib/siteIcon'

/** Иконка вкладки браузера и ярлыка сайта. */
export default function SiteIconCard() {
  // номер меняется после загрузки, чтобы картинка не бралась из кэша
  const [version, setVersion] = useState(() => Date.now())
  const [missing, setMissing] = useState(false)
  const changed = () => {
    const next = Date.now()
    setVersion(next)
    setMissing(false)
    refreshSiteIcon(next)
  }
  const upload = useMutation({
    mutationFn: (file: File) => api('/admin/site-icon', { method: 'POST', file }),
    onSuccess: changed,
  })
  const remove = useMutation({
    mutationFn: () => api('/admin/site-icon', { method: 'DELETE' }),
    onSuccess: changed,
  })

  return (
    <Card title="Иконка сайта">
      {missing ? (
        <p className="text-sm">Иконка не загружена.</p>
      ) : (
        <div className="flex items-center gap-3">
          <img
            src={`${SITE_ICON_URL}?v=${version}`}
            alt="Текущая иконка сайта"
            className="size-16 rounded-lg border border-slate-200 object-contain dark:border-slate-700"
            onError={() => setMissing(true)}
          />
          <Button variant="danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
            Убрать
          </Button>
        </div>
      )}
      <FileDrop
        title={missing ? 'Загрузить иконку' : 'Заменить иконку'}
        hint="Квадратная картинка PNG, ICO, SVG, JPG или WEBP, до 2 МБ. Лучше PNG 512×512."
        accept=".png,.ico,.svg,.jpg,.jpeg,.webp,.gif,image/*"
        disabled={upload.isPending}
        onFiles={([file]) => upload.mutate(file)}
      />
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Видна на вкладке браузера и на ярлыке сайта. Картинку бота и Mini App меняют в
        @BotFather.
      </p>
      <ErrorText error={upload.error ?? remove.error} />
    </Card>
  )
}
