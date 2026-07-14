import {
  Alert,
  Button,
  Center,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useLogin, useMe } from '../hooks/useAuth'

export function LoginPage() {
  const { data: user, isLoading } = useMe()
  const login = useLogin()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  if (!isLoading && user) {
    return <Navigate to="/dashboard" replace />
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await login.mutateAsync({ username, password })
      const from = (location.state as { from?: string } | null)?.from || '/dashboard'
      navigate(from, { replace: true })
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : '登录失败，请检查用户名或密码'
      setError(message)
    }
  }

  return (
    <Center mih="100vh" px="md">
      <Paper withBorder p="xl" w={400} radius="md" shadow="sm">
        <Stack gap="md">
          <div>
            <Title order={2}>TG-forwarder</Title>
            <Text c="dimmed" size="sm">
              管理面板登录
            </Text>
          </div>
          {error && (
            <Alert color="red" title="无法登录">
              {error}
            </Alert>
          )}
          <form onSubmit={onSubmit}>
            <Stack gap="sm">
              <TextInput
                label="用户名"
                value={username}
                onChange={(e) => setUsername(e.currentTarget.value)}
                required
                autoFocus
              />
              <PasswordInput
                label="密码"
                value={password}
                onChange={(e) => setPassword(e.currentTarget.value)}
                required
              />
              <Button type="submit" loading={login.isPending} fullWidth>
                登录
              </Button>
            </Stack>
          </form>
        </Stack>
      </Paper>
    </Center>
  )
}
