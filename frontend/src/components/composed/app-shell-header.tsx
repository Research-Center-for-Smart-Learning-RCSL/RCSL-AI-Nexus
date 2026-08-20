import type { Dispatch, RefObject, SetStateAction } from 'react';
import Link from 'next/link';
import { LogOutIcon, MenuIcon, SparklesIcon, UserCogIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ThemeToggle } from '@/components/composed/theme-toggle';
import type { AuthMode, Me } from '@/lib/session';
import { cn } from '@/lib/utils';

type Props = { navButtonRef: RefObject<HTMLButtonElement | null>; navOpen: boolean; setNavOpen: Dispatch<SetStateAction<boolean>>; me: Me; authMode: AuthMode | null; assistant: { isOpen: boolean; setOpen: (open: boolean) => void }; signOut: () => Promise<void> };

export function AppShellHeader({ navButtonRef, navOpen, setNavOpen, me, authMode, assistant, signOut }: Props) {
  return (
          <header className="flex items-center justify-between gap-3 border-b px-4 py-2">
            <div className="flex min-w-0 items-center gap-2">
              <Button
                ref={navButtonRef}
                variant="ghost"
                size="icon-sm"
                className="sm:hidden"
                aria-label="Open the menu"
                aria-expanded={navOpen}
                onClick={() => setNavOpen(true)}
              >
                <MenuIcon />
              </Button>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{me.display_name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {me.login} - {me.role}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
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
                  'gap-1.5',
                  assistant.isOpen && 'bg-muted text-foreground',
                )}
              >
                <SparklesIcon className="size-4" />
                <span className="hidden sm:inline">Assistant</span>
              </Button>
              <ThemeToggle />
              {/* Account settings only apply where local credentials exist. */}
              {authMode !== 'tailnet' ? (
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label="Account"
                  // This renders an anchor, not a button. Without saying so,
                  // Base UI keeps native button semantics for an element that
                  // has none, and warns. A link that navigates is the correct
                  // element here — it is Ctrl-clickable and has an href — so
                  // the prop follows the markup rather than the other way.
                  nativeButton={false}
                  render={<Link href="/account" />}
                >
                  <UserCogIcon />
                  {/* The label is the first thing to go when the header has to
                      share a narrow row with the menu button and the identity
                      block; the icon still carries the meaning, and the
                      aria-label above keeps the name for anyone not seeing it. */}
                  <span className="hidden md:inline">Account</span>
                </Button>
              ) : null}
              {/* No session on the tailnet, so nothing to sign out of. */}
              {authMode !== 'tailnet' ? (
                <Button
                  variant="outline"
                  size="sm"
                  aria-label="Sign out"
                  onClick={() => void signOut()}
                >
                  <LogOutIcon />
                  <span className="hidden md:inline">Sign out</span>
                </Button>
              ) : null}
            </div>
          </header>
  );
}
