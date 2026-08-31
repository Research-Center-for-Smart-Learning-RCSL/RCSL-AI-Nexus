import type { Dispatch, RefObject, SetStateAction } from 'react';
import Link from 'next/link';
import {
  CircleUserRoundIcon,
  LogOutIcon,
  MenuIcon,
  SparklesIcon,
  UserCogIcon,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Menu as AccountMenu,
  MenuContent,
  MenuGroup,
  MenuItem,
  MenuLabel,
  MenuLinkItem,
  MenuSeparator,
  MenuTrigger,
} from '@/components/ui/menu';
import { ThemeMenuItem } from '@/components/composed/theme-toggle';
import { ROLE_LABELS } from '@/features/users/schema';
import type { AuthMode, Me } from '@/lib/session';
import { cn } from '@/lib/utils';

type Props = { navButtonRef: RefObject<HTMLButtonElement | null>; navOpen: boolean; setNavOpen: Dispatch<SetStateAction<boolean>>; me: Me; authMode: AuthMode | null; assistant: { isOpen: boolean; setOpen: (open: boolean) => void }; signOut: () => Promise<void> };

export function AppShellHeader({ navButtonRef, navOpen, setNavOpen, me, authMode, assistant, signOut }: Props) {
  const hasLocalSession = authMode === 'local';

  return (
          <header className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-2">
            <div className="flex min-w-0 items-center gap-2">
              <Button
                ref={navButtonRef}
                variant="ghost"
                size="icon-sm"
                className="lg:hidden"
                aria-label="Open the menu"
                aria-expanded={navOpen}
                onClick={() => setNavOpen(true)}
              >
                <MenuIcon />
              </Button>
              <Link
                href="/"
                aria-label="RCSL AI Nexus, home"
                className="shrink-0 rounded-sm font-heading text-sm font-semibold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:hidden"
              >
                AI Nexus
              </Link>
            </div>
            <div className="flex shrink-0 items-center gap-1 sm:gap-2">
              {/* Labelled, not just an icon. The sparkle alone said nothing
                  about what it opens — an operator has to already know the
                  feature exists to try it, which is the opposite of what an
                  assistant is for. The text is what the `aria-label` has always
                  said, so a screen reader user was the only one being told.
                  Hidden below `sm` where the header is tight; the label is what
                  drops, never the control. */}
              <Button
                variant="ghost"
                size="sm"
                aria-label={
                  assistant.isOpen
                    ? 'Close the assistant'
                    : 'Open the assistant'
                }
                aria-expanded={assistant.isOpen}
                onClick={() => assistant.setOpen(!assistant.isOpen)}
                className={cn(
                  'gap-1.5 max-sm:size-7 max-sm:p-0',
                  assistant.isOpen && 'bg-muted text-foreground',
                )}
              >
                <SparklesIcon className="size-4" />
                <span className="hidden sm:inline">Assistant</span>
              </Button>
              <AccountMenu>
                <MenuTrigger
                  className="inline-flex min-h-7 max-w-[min(20rem,42vw)] min-w-7 items-center justify-center rounded-[min(var(--radius-md),12px)] px-1.5 outline-none transition-colors hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-expanded:bg-muted md:justify-start md:px-2 [&_svg]:size-4"
                  aria-label="Open account and appearance menu"
                >
                  <CircleUserRoundIcon className="md:hidden" />
                  <span className="hidden min-w-0 text-left md:block">
                    <span className="block truncate text-sm font-medium text-foreground">
                      {me.display_name}
                    </span>
                    <span className="block truncate text-xs font-normal text-muted-foreground">
                      {me.login} – {ROLE_LABELS[me.role] ?? me.role}
                    </span>
                  </span>
                </MenuTrigger>
                <MenuContent className="w-80">
                  <MenuGroup>
                    <MenuLabel>
                      <span className="block whitespace-normal text-sm font-medium text-foreground [overflow-wrap:anywhere]">
                        {me.display_name}
                      </span>
                      <span className="block whitespace-normal text-xs font-normal text-muted-foreground [overflow-wrap:anywhere]">
                        {me.login} – {ROLE_LABELS[me.role] ?? me.role}
                      </span>
                    </MenuLabel>
                    <MenuSeparator />
                    <ThemeMenuItem />
                    {hasLocalSession ? (
                      <MenuLinkItem
                        closeOnClick
                        render={<Link href="/account" />}
                      >
                        <UserCogIcon />
                        <span>Account settings</span>
                      </MenuLinkItem>
                    ) : null}
                    {hasLocalSession ? (
                      <MenuItem
                        className="text-destructive data-highlighted:bg-destructive/10 data-highlighted:text-destructive"
                        onClick={() => void signOut()}
                      >
                        <LogOutIcon />
                        <span>Sign out</span>
                      </MenuItem>
                    ) : null}
                  </MenuGroup>
                </MenuContent>
              </AccountMenu>
            </div>
          </header>
  );
}
