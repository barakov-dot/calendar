/** Окна поверх страницы: «Назад» сначала закрывает их, а не уводит со страницы. */
const overlays: (() => void)[] = []

export function coverBack(close: () => void): () => void {
  overlays.push(close)
  return () => {
    const index = overlays.lastIndexOf(close)
    if (index >= 0) overlays.splice(index, 1)
  }
}

/** Закрывает верхнее окно; false — закрывать было нечего. */
export function closeTopOverlay(): boolean {
  const close = overlays.at(-1)
  close?.()
  return close !== undefined
}
