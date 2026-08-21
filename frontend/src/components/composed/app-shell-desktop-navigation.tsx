import { Badge } from '@/components/ui/badge';
import { Logo } from '@/components/composed/logo';
import { authModeLabel, type AuthMode } from '@/lib/session';

import { NavGroups } from './app-shell-navigation';
import type { NavGroup, NavItem } from './app-shell-navigation-catalog';

type Props = { authMode: AuthMode | null; pinned: NavItem[]; groups: NavGroup[]; pathname: string | null; collapsed: Set<string>; onToggle: (id: string) => void };

export function DesktopNavigation({ authMode, pinned: visiblePinned, groups: visibleGroups, pathname, collapsed, onToggle: toggleGroup }: Props) {
  return (
        <aside className="hidden h-full w-56 shrink-0 overflow-y-auto overscroll-contain border-r p-3 lg:block">
          <div className="mb-4 px-2">
            {/* Stacked rather than set beside the title. The sidebar is 224px
                wide, which leaves room for the mark at a size it survives;
                inline next to the text it would have to shrink to about 24px,
                where the monogram becomes an unreadable blob. */}
            <Logo height={48} className="mb-2" />
            <p className="font-heading text-sm font-semibold">RCSL AI Nexus</p>
            <Badge variant="outline" className="mt-1">
              {authModeLabel(authMode)}
            </Badge>
          </div>
          <NavGroups
            label="Screens"
            pinned={visiblePinned}
            groups={visibleGroups}
            pathname={pathname}
            collapsed={collapsed}
            onToggle={toggleGroup}
          />
        </aside>
  );
}
