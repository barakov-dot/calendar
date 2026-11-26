import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '../../lib/api'
import type { SettingsResponse } from '../../lib/types'

export const SETTINGS_KEY = ['settings']

export interface Patch {
  settings?: Record<string, unknown>
  clear?: string[]
}

export function useSaveSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: Patch) =>
      api<SettingsResponse>('/admin/settings', { method: 'PATCH', body: patch }),
    onSuccess: (data) => {
      queryClient.setQueryData(SETTINGS_KEY, data)
      void queryClient.invalidateQueries({ queryKey: ['backups'] })
    },
  })
}
