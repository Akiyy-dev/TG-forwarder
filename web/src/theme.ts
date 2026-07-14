import { createTheme } from '@mantine/core'

export const theme = createTheme({
  fontFamily:
    'system-ui, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
  primaryColor: 'teal',
  defaultRadius: 'md',
  colors: {
    // Keep brand off purple defaults; teal reads clearly in dark admin UI.
  },
})
