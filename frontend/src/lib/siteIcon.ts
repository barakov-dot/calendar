export const SITE_ICON_URL = '/api/site-icon'

/** Заставляет браузер взять новую иконку вкладки без перезагрузки страницы. */
export function refreshSiteIcon(version: number): void {
  for (const link of document.querySelectorAll<HTMLLinkElement>('link[data-site-icon]')) {
    link.href = `${SITE_ICON_URL}?v=${version}`
  }
}
