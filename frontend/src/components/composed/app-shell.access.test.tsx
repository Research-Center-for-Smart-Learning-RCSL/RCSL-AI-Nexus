import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { replace, SCOPES, signedInWith, TestAppShell } from './app-shell-test-support';

// The nav renders whatever `can` answers, so what `can` answers when the server
// reports no scopes at all belongs with `can` itself: see lib/session.test.tsx.

describe('a URL the account has no scope for', () => {
  it('is redirected to the one screen everybody can use', () => {
    // The nav hides the link; this covers the address bar, a bookmark, and a
    // link pasted by somebody with more scopes than the reader.
    signedInWith(SCOPES.user, '/users');
    render(<TestAppShell>content</TestAppShell>);

    expect(replace).toHaveBeenCalledWith('/chat');
  });

  it('leaves a permitted screen alone', () => {
    signedInWith(SCOPES.user, '/usage');
    render(<TestAppShell>content</TestAppShell>);

    expect(replace).not.toHaveBeenCalled();
  });

  it('sends a member off the dashboard, which is the index everyone opens', () => {
    // `/` requires `usage:read_all`, so for a member the landing page is one
    // they cannot read. Without the guard they would arrive on a 403 rather
    // than anywhere useful.
    signedInWith(SCOPES.user, '/');
    render(<TestAppShell>content</TestAppShell>);

    expect(replace).toHaveBeenCalledWith('/chat');
  });

  it('leaves the dashboard alone for someone who can read it', () => {
    signedInWith(SCOPES.operator, '/');
    render(<TestAppShell>content</TestAppShell>);

    expect(replace).not.toHaveBeenCalled();
  });

  it('does not render the screen it is redirecting away from', () => {
    // The redirect is an effect, so it cannot pre-empt the mount; only not
    // rendering the children can. What mounts sends its queries, and each
    // refusal is an `authz.denied` audit row — so before this, every sign-in
    // by a member wrote two, for scopes they were never shown a link to.
    signedInWith(SCOPES.user, '/');
    render(<TestAppShell>content</TestAppShell>);

    expect(replace).toHaveBeenCalledWith('/chat');
    expect(screen.queryByText('content')).not.toBeInTheDocument();
  });

  it('still renders a permitted screen', () => {
    signedInWith(SCOPES.user, '/usage');
    render(<TestAppShell>content</TestAppShell>);

    expect(screen.getByText('content')).toBeInTheDocument();
  });
});
