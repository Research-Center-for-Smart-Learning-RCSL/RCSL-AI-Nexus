import type { Dispatch, RefObject, SetStateAction } from 'react';
import { XIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { authModeLabel, type AuthMode } from '@/lib/session';

import { NavGroups } from './app-shell-navigation';
import type { NavGroup, NavItem } from './app-shell-navigation-catalog';

type Props = { navMounted: boolean; navPanelState: 'open' | 'closed'; navClosing: boolean; setNavOpen: Dispatch<SetStateAction<boolean>>; navPanelRef: RefObject<HTMLDivElement | null>; authMode: AuthMode | null; pinned: NavItem[]; groups: NavGroup[]; pathname: string | null; collapsed: Set<string>; onToggle: (id: string) => void };

export function MobileNavigation({ navMounted, navPanelState, navClosing, setNavOpen, navPanelRef, authMode, pinned: visiblePinned, groups: visibleGroups, pathname, collapsed, onToggle: toggleGroup }: Props) {
  return (
    <>
{navMounted ? (
          <div className="fixed inset-0 z-50 lg:hidden">
            <button
              type="button"
              aria-label="Close the menu"
              aria-hidden="true"
              tabIndex={-1}
              disabled={navClosing}
              data-panel-state={navPanelState}
              className="nexus-panel-backdrop nexus-panel-motion absolute inset-0 bg-black/40"
              onClick={() => setNavOpen(false)}
            />
            <div
              ref={navPanelRef}
              role="dialog"
              aria-modal="true"
              aria-label="Navigation"
              aria-hidden={navClosing || undefined}
              inert={navClosing || undefined}
              data-panel-state={navPanelState}
              // Focusable only as a target for the effect above, so focus lands
              // inside the panel and Tab continues through the links rather
              // than leaving for the header.
              tabIndex={-1}
              className="nexus-panel-from-inline-start nexus-panel-motion absolute inset-y-0 left-0 flex w-64 max-w-[85%] flex-col overflow-y-auto overscroll-contain border-r bg-background p-3 outline-none"
            >
              <div className="mb-4 flex items-start justify-between gap-2 px-2">
                <div>
                  <p className="font-heading text-sm font-semibold">
                    RCSL AI Nexus
                  </p>
                  <Badge variant="outline" className="mt-1">
                    {authModeLabel(authMode)}
                  </Badge>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Close the menu"
                  onClick={() => {
                    setNavOpen(false);
                  }}
                >
                  <XIcon />
                </Button>
              </div>
              <NavGroups
                label="Screens, in the menu"
                pinned={visiblePinned}
                groups={visibleGroups}
                pathname={pathname}
                collapsed={collapsed}
                onToggle={toggleGroup}
                onNavigate={() => setNavOpen(false)}
              />
            </div>
          </div>
        ) : null}
    </>
  );
}
