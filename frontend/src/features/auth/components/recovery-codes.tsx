'use client';

/**
 * Recovery codes are hashed at rest and displayed exactly once at enrolment
 * (security.md section 5.3). The explicit acknowledgement is not politeness:
 * without it, the natural next click dismisses the only copy that will ever
 * exist, and recovering the account then needs an administrator.
 */

import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { OneTimeSecret } from '@/components/composed/one-time-secret';
import { RECOVERY_CODES_WARNING } from '@/features/auth/messages';

export type RecoveryCodesProps = {
  codes: string[];
  continueLabel?: string;
  onContinue: () => void;
};

export function RecoveryCodes({
  codes,
  continueLabel = 'Continue',
  onContinue,
}: RecoveryCodesProps) {
  const [acknowledged, setAcknowledged] = useState(false);

  return (
    <div className="space-y-4">
      <OneTimeSecret
        title="Your recovery codes"
        description={RECOVERY_CODES_WARNING}
        values={codes}
        acknowledgement="I have saved these"
        onAcknowledgedChange={setAcknowledged}
      />
      <Button
        className="w-full"
        disabled={!acknowledged}
        onClick={onContinue}
        type="button"
      >
        {continueLabel}
      </Button>
      {!acknowledged ? (
        <p className="text-center text-xs text-muted-foreground">
          Confirm you have saved them to continue. They cannot be shown again.
        </p>
      ) : null}
    </div>
  );
}
