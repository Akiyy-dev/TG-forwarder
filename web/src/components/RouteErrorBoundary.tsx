import { Button, Stack, Text, Title } from '@mantine/core'
import { Component, type ErrorInfo, type ReactNode } from 'react'

type Props = { children: ReactNode }
type State = { error: Error | null }

export class RouteErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('route_render_failed', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <Stack align="center" justify="center" mih="50vh" gap="md">
        <Title order={3}>页面渲染失败</Title>
        <Text c="dimmed" size="sm" maw={480} ta="center">
          {this.state.error.message}
        </Text>
        <Button
          onClick={() => {
            this.setState({ error: null })
            window.location.assign('/dashboard')
          }}
        >
          返回仪表盘
        </Button>
      </Stack>
    )
  }
}
