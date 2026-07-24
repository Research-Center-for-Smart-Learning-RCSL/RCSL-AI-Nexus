'use client';

import { cn } from '@/lib/utils';
import { usePasswordStrength } from '@/features/auth/hooks/use-password-strength';
import { PASSWORD_MIN_LENGTH } from '@/features/auth/password-schema';

const LABELS = ['Very weak', 'Weak', 'Fair', 'Good', 'Strong'] as const;
const TONES = [
  'bg-destructive',
  'bg-destructive',
  'bg-amber-500',
  'bg-emerald-500',
  'bg-emerald-500',
] as const;

export function PasswordStrengthMeter({
  password,
  className,
}: {
  password: string;
  className?: string;
}) {
  const strength = usePasswordStrength(password);
  const tooShort = password.length > 0 && password.length < PASSWORD_MIN_LENGTH;

  return (
    <div className={cn('space-y-1.5', className)} aria-live="polite">
      <div className="flex gap-1">
        {[0, 1, 2, 3, 4].map((index) => (
          <div
            key={index}
            className={cn(
              'h-1 flex-1 rounded-full bg-muted',
              password && index <= strength.score && TONES[strength.score],
            )}
          />
        ))}
      </div>
      {password ? (
        <p className="text-xs text-muted-foreground">
          {LABELS[strength.score]}
          {tooShort ? ` - at least ${PASSWORD_MIN_LENGTH} characters` : ''}
          {strength.warning ? ` - ${strength.warning}` : ''}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          At least {PASSWORD_MIN_LENGTH} characters. No composition rules; length
          and unpredictability are what count.
        </p>
      )}
      {strength.suggestions.length > 0 && !strength.meetsThreshold ? (
        <ul className="list-disc pl-4 text-xs text-muted-foreground">
          {strength.suggestions.map((suggestion) => (
            <li key={suggestion}>{suggestion}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

