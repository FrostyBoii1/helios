// TanStack Query hooks for tasks + the selectable-users picker.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  completeTask,
  createTask,
  deleteTask,
  listSelectableUsers,
  listTasks,
  reopenTask,
  updateTask,
  type ListTasksParams,
} from '@/lib/tasks'
import type { TaskInput } from '@/types'

const keys = {
  all: ['tasks'] as const,
  list: (params: ListTasksParams) => ['tasks', 'list', params] as const,
}

export function useTasks(params: ListTasksParams) {
  return useQuery({
    queryKey: keys.list(params),
    queryFn: () => listTasks(params),
  })
}

export function useSelectableUsers() {
  return useQuery({
    queryKey: ['users', 'selectable'],
    queryFn: () => listSelectableUsers(),
    staleTime: 5 * 60_000,
  })
}

function useInvalidateTasks() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: keys.all })
}

export function useCreateTask() {
  const invalidate = useInvalidateTasks()
  return useMutation({
    mutationFn: (input: TaskInput) => createTask(input),
    onSuccess: () => void invalidate(),
  })
}

export function useUpdateTask(id: number) {
  const invalidate = useInvalidateTasks()
  return useMutation({
    mutationFn: (input: TaskInput) => updateTask(id, input),
    onSuccess: () => void invalidate(),
  })
}

export function useCompleteTask() {
  const invalidate = useInvalidateTasks()
  return useMutation({
    mutationFn: ({ id, notes }: { id: number; notes?: string }) => completeTask(id, notes),
    onSuccess: () => void invalidate(),
  })
}

export function useReopenTask() {
  const invalidate = useInvalidateTasks()
  return useMutation({
    mutationFn: (id: number) => reopenTask(id),
    onSuccess: () => void invalidate(),
  })
}

export function useDeleteTask() {
  const invalidate = useInvalidateTasks()
  return useMutation({
    mutationFn: (id: number) => deleteTask(id),
    onSuccess: () => void invalidate(),
  })
}
