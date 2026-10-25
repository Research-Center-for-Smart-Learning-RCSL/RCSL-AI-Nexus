import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import {
  closeForMaintenance,
  maintenanceState,
  maintenanceUnknown,
  replace,
  SCOPES,
  signedInAs,
  signedInWith,
  signedOut,
  TestAppShell,
} from './app-shell-test-support';

/**
 * The shell during a maintenance hold (#61). Who sees the platform and who sees
 * the maintenance page is decided here, ahead of the login redirect; the
 * backend refuses everyone else whatever this renders, so what is pinned is
 * that nobody is sent to fix a session or a connection that is not broken.
 */
describe('the app shell during maintenance', () => {
  it('shows a member the maintenance page instead of the screen', () => {
    signedInWith(SCOPES.user, '/chat');
    closeForMaintenance();
    render(<TestAppShell>secret screen</TestAppShell>);

    expect(screen.getByRole('heading', { name: 'Closed for maintenance' })).toBeInTheDocument();
    expect(screen.getByText('Upgrading the runtime')).toBeInTheDocument();
    expect(screen.queryByText('secret screen')).not.toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('keeps a platform administrator in the shell, under a banner', () => {
    closeForMaintenance();
    signedInWith(SCOPES.admin);
    signedInAs('admin');
    render(<TestAppShell>admin screen</TestAppShell>);

    expect(screen.getByText('admin screen')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Manage maintenance' })).toHaveAttribute(
      'href',
      '/maintenance',
    );
  });

  it('changes nothing while the platform is open', () => {
    signedInWith(SCOPES.user, '/chat');
    render(<TestAppShell>ordinary screen</TestAppShell>);

    expect(screen.getByText('ordinary screen')).toBeInTheDocument();
    expect(screen.queryByText(/Closed for maintenance/)).not.toBeInTheDocument();
  });

  it('does not send anyone to sign in before the status is known', () => {
    // An anonymous `/me` 401 that lands before the first status answer must
    // not redirect: the answer may yet be "closed", and the maintenance page
    // is what such a reader should see.
    signedInWith(SCOPES.user, '/chat');
    signedOut();
    maintenanceUnknown();
    render(<TestAppShell>secret screen</TestAppShell>);

    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('Checking your access');
    expect(screen.queryByText('secret screen')).not.toBeInTheDocument();
  });

  it('shows the maintenance page, not the login, once the status says closed', () => {
    signedInWith(SCOPES.user, '/chat');
    signedOut();
    closeForMaintenance();
    render(<TestAppShell>secret screen</TestAppShell>);

    expect(screen.getByRole('heading', { name: 'Closed for maintenance' })).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('does not assume open when the first status read fails', () => {
    signedInWith(SCOPES.admin);
    signedInAs('admin');
    maintenanceUnknown(true);
    render(<TestAppShell>cached screen</TestAppShell>);

    expect(screen.getByText('Could not check whether the platform is open')).toBeInTheDocument();
    expect(screen.queryByText('cached screen')).not.toBeInTheDocument();
    screen.getByRole('button', { name: 'Try again' }).click();
    expect(maintenanceState.refresh).toHaveBeenCalled();
  });
});
