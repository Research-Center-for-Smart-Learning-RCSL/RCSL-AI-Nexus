'use client';

import { CheckIcon } from 'lucide-react';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useRoles } from '@/features/users/hooks/use-users';
import {
  roleSchema,
  ROLE_DESCRIPTIONS,
  ROLE_LABELS,
  SCOPE_LABELS,
  type Role,
} from '@/features/users/schema';

/**
 * Choosing a role, with what the role means shown next to it.
 *
 * The picker was a list of six words. Six words are enough to choose between
 * `admin` and `user` and not nearly enough to choose between `operator` and
 * `tenant_admin`, which differ in exactly the way that matters — one runs the
 * hardware and grants nobody access, the other grants access and cannot touch
 * the hardware. Whoever is assigning a role is the person least likely to have
 * read `role_authorization.py`.
 *
 * Two layers, because they fail differently. The sentence is copy and lives in
 * `ROLE_DESCRIPTIONS`; the permission list is fetched from `GET /admin/roles`,
 * which is generated from the table the backend enforces. If the wording drifts
 * it reads oddly. If it were the *only* thing shown, it could be wrong about
 * what a role grants, and nobody would find out from this screen.
 */
export function RolePicker({
  value,
  onChange,
  disabled,
}: {
  value: Role;
  onChange: (role: Role) => void;
  disabled?: boolean;
}) {
  const { data: catalogue } = useRoles();
  const scopes = catalogue?.find((entry) => entry.role === value)?.scopes;

  return (
    <div className="space-y-2">
      <Select
        value={value}
        onValueChange={(next) => onChange(next as Role)}
        disabled={disabled}
      >
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {roleSchema.options.map((role) => (
            <SelectItem key={role} value={role}>
              {ROLE_LABELS[role]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <p className="text-sm text-muted-foreground">
        {ROLE_DESCRIPTIONS[value]}
      </p>

      {/* Absent while the catalogue loads rather than replaced by a spinner:
          the sentence above already answers the question, and a box that
          changes height under the cursor is worse than one that fills in. */}
      {scopes ? (
        <div className="rounded-lg border bg-muted/30 p-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            {ROLE_LABELS[value]} can:
          </p>
          <ul className="grid gap-1 sm:grid-cols-2">
            {scopes.map((scope) => (
              <li
                key={scope}
                className="flex items-start gap-1.5 text-xs text-muted-foreground"
              >
                <CheckIcon
                  className="mt-0.5 size-3 shrink-0 text-primary"
                  aria-hidden
                />
                {/* Falls back to the identifier. A permission with no wording
                    is still shown, because leaving it out would understate
                    what the role grants — the one direction this must not be
                    wrong in. */}
                <span>{SCOPE_LABELS[scope] ?? scope}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
