import { Center, Loader } from '@mantine/core'
import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { isUnauthorized, useMe } from '../hooks/useAuth'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { data, isLoading, error } = useMe()

  if (isLoading) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    )
  }

  if (error || !data || isUnauthorized(error)) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <>{children}</>
}
