import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './api'
import type { TaskListResponse, TaskStatus } from './tasks'

export const PAGE_LIMIT = 2000

export type TaskFilters = Record<string, string | number | boolean | undefined | null>

export function useTasks(filters: TaskFilters) {
  const params = new URLSearchParams({ limit: String(PAGE_LIMIT) })
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  return useQuery({
    queryKey: ['tasks', params.toString()],
    queryFn: () => api<TaskListResponse>(`/tasks?${params}`),
    refetchOnMount: 'always',
  })
}

/** После изменения задач перечитываются списки, карточки и пометки компаний. */
export function useRefreshTasks() {
  const queryClient = useQueryClient()
  return () => {
    for (const key of ['tasks', 'task', 'companies']) {
      void queryClient.invalidateQueries({ queryKey: [key] })
    }
  }
}

export function useBulkStatus(onDone: () => void) {
  const refresh = useRefreshTasks()
  return useMutation({
    mutationFn: (body: { ids: number[]; status: TaskStatus }) =>
      api<{ updated: number; skipped: number }>('/tasks/bulk', { method: 'POST', body }),
    onSuccess: () => {
      onDone()
      refresh()
    },
  })
}
