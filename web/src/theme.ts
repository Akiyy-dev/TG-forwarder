import { createTheme, rem } from '@mantine/core'

export const theme = createTheme({
  fontFamily:
    '"IBM Plex Sans", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif',
  fontFamilyMonospace: '"IBM Plex Mono", ui-monospace, monospace',
  headings: {
    fontFamily:
      '"IBM Plex Sans", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif',
    fontWeight: '600',
  },
  primaryColor: 'teal',
  defaultRadius: 'md',
  spacing: {
    xs: rem(6),
    sm: rem(10),
    md: rem(16),
    lg: rem(22),
    xl: rem(32),
  },
  components: {
    AppShell: {
      styles: {
        header: {
          background:
            'linear-gradient(180deg, rgba(18, 28, 32, 0.96), rgba(14, 22, 26, 0.92))',
          borderBottom: '1px solid rgba(94, 234, 212, 0.12)',
          backdropFilter: 'blur(10px)',
        },
        navbar: {
          background: 'rgba(12, 18, 22, 0.92)',
          borderRight: '1px solid rgba(148, 163, 184, 0.12)',
        },
        main: {
          background:
            'radial-gradient(1200px 600px at 10% -10%, rgba(45, 212, 191, 0.08), transparent 50%), radial-gradient(900px 500px at 100% 0%, rgba(14, 165, 233, 0.06), transparent 45%), #0b1216',
        },
      },
    },
    Table: {
      styles: {
        th: { fontSize: rem(12), letterSpacing: '0.02em' },
      },
    },
    Modal: {
      styles: {
        content: {
          animation: 'modalIn 180ms ease-out',
        },
      },
    },
  },
})
