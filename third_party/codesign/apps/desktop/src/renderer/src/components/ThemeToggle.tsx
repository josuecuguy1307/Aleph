import { useT } from '@open-codesign/i18n';
import { IconButton } from '@open-codesign/ui';
import { Moon, Sun } from 'lucide-react';
import { useCodesignStore } from '../store';

export function ThemeToggle() {
  const t = useT();
  const theme = useCodesignStore((s) => s.theme);
  const toggle = useCodesignStore((s) => s.toggleTheme);
  const isDark = theme === 'dark';
  return (
    <IconButton label={t('theme.toggleAria')} size="md" onClick={toggle}>
      {isDark ? <Sun className="w-[18px] h-[18px]" /> : <Moon className="w-[18px] h-[18px]" />}
    </IconButton>
  );
}
