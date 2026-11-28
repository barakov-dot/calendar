import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { closeTopOverlay } from '../lib/backStack'
import { miniAppInitData, showBackButton } from '../lib/telegram'

/** Куда вернуться, если Mini App открыли сразу на этой странице. */
function parentOf(path: string, client: boolean): string {
  const list = /^\/(companies|demands|users)\/./.exec(path)
  if (list) return `/${list[1]}`
  const inMore =
    /^\/(companies|declarations|preferences|reminders|reports|users|broadcasts|accountants|settings|signatures)\b/
  return !client && inMore.test(path) ? '/more' : '/'
}

/** Стрелка «Назад» в шапке Mini App на всех страницах, кроме главной. */
export default function TelegramBack({ client }: { client: boolean }) {
  const path = useLocation().pathname
  const navigate = useNavigate()
  const home = path === '/'
  const back = useRef(() => {})

  useEffect(() => {
    back.current = () => {
      if (closeTopOverlay()) return
      // idx — номер страницы в истории приложения, его ведёт react-router
      const state = window.history.state as { idx?: number } | null
      if (state?.idx) void navigate(-1)
      else void navigate(parentOf(path, client), { replace: true })
    }
  }, [path, client, navigate])

  useEffect(() => {
    if (home || !miniAppInitData()) return
    return showBackButton(() => back.current())
  }, [home])

  return null
}
