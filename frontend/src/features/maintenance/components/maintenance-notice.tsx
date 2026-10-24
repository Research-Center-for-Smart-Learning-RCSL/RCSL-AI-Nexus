'use client';

import { useMaintenance } from '@/lib/maintenance';

import { formatExpectedReturn } from '../format';

/**
 * Above the sign-in screens while the platform is closed (#61). Sign-in stays
 * open, because administrators need it; this says who it is open to before
 * anyone else types a password for nothing.
 */
export function MaintenanceNotice() {
  const { closed, status } = useMaintenance();
  if (!closed || !status) return null;
  const back = formatExpectedReturn(status.expected_return_at);
  return (
    <div
      role="status"
      className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm"
    >
      <p className="font-medium">Closed for maintenance</p>
      <p className="text-muted-foreground">
        {status.message ?? 'Only platform administrators can sign in until it reopens.'}
      </p>
      {back ? <p className="mt-1">Expected back: {back}</p> : null}
    </div>
  );
}
