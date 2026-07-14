import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchMe, login, logout } from '../api/auth'
import { ApiError } from '../api/client'

export function useMe() {
  return useQuery({
    queryKey: ['auth', 'me'],
    queryFn: fetchMe,
    retry: false,
    staleTime: 30_000,
  })
}

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      login(username, password),
    onSuccess: (data) => {
      qc.setQueryData(['auth', 'me'], data.user)
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: logout,
    onSettled: () => {
      qc.clear()
    },
  })
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}
