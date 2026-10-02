import { Menu } from 'electron';

export function registerAppMenu(): void {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      role: 'appMenu' as const,
    },
    {
      role: 'fileMenu' as const,
    },
    {
      role: 'editMenu' as const,
    },
    {
      role: 'viewMenu' as const,
    },
    {
      role: 'windowMenu' as const,
    },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}
