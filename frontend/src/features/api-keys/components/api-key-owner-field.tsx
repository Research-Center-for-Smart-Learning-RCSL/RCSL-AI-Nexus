import type { Control } from 'react-hook-form';

import { FormField } from '@/components/composed/form-field';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { CreateApiKeyInput } from '@/features/api-keys/schema';
import type { User } from '@/features/users/schema';

export function ApiKeyOwnerField({
  control,
  owners,
  isLoading,
}: {
  control: Control<CreateApiKeyInput>;
  owners: User[];
  isLoading: boolean;
}) {
  return (
    <FormField
      control={control}
      name="owner_id"
      label="Owner"
      description="Who holds this key. Revoke it when they leave; deleting the account takes its keys with it."
      render={(field) => (
        <Select
          value={field.value as string}
          onValueChange={(value) => field.onChange(value)}
          disabled={isLoading}
        >
          <SelectTrigger className="w-full">
            <SelectValue placeholder={isLoading ? 'Loading...' : 'Choose an owner'} />
          </SelectTrigger>
          <SelectContent>
            {owners.map((user) => (
              <SelectItem key={user.id} value={user.id}>
                {user.display_name} ({user.login})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    />
  );
}
