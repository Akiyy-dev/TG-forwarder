import { Button, Stack, Text, Title } from '@mantine/core'
import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <Stack align="center" justify="center" mih="60vh" gap="md">
      <Title order={2}>页面不存在</Title>
      <Text c="dimmed">该路径尚未实现或不存在。</Text>
      <Button component={Link} to="/dashboard">
        返回仪表盘
      </Button>
    </Stack>
  )
}
