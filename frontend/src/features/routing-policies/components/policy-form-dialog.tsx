'use client';

import { useForm, useFieldArray } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Form } from '@/components/ui/form';
import { FormField } from '@/components/composed/form-field';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { describeError } from '@/components/composed/error-state';
import type { Capability } from '@/features/models/schema';
import {
  savePolicyFormSchema,
  thinkingToApi,
  type RoutingPolicy,
  type SavePolicyInput,
  type SavePolicyValues,
} from '@/features/routing-policies/schema';
import { useSaveRoutingPolicy } from '@/features/routing-policies/hooks/use-routing-policies';
import { PolicyCandidatesEditor } from './policy-candidates-editor';
import { policyFormDefaults } from './policy-form-defaults';

export type PolicyFormDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Absent when creating a policy for a capability that has none. */
  policy?: RoutingPolicy;
  /** Capabilities selectable when creating. Ignored (fixed) when editing. */
  capabilityOptions: Capability[];
  /** Registered model aliases, offered as a select when the list has arrived. */
  modelAliases?: string[];
};

export function PolicyFormDialog({
  open,
  onOpenChange,
  policy,
  capabilityOptions,
  modelAliases = [],
}: PolicyFormDialogProps) {
  const isEdit = Boolean(policy);
  const save = useSaveRoutingPolicy();
  const initialCapability = policy?.capability ?? capabilityOptions[0] ?? 'chat';

  const form = useForm<SavePolicyInput, unknown, SavePolicyValues>({
    resolver: zodResolver(savePolicyFormSchema),
    defaultValues: policyFormDefaults(policy, initialCapability),
  });

  const candidates = useFieldArray({ control: form.control, name: 'candidates' });

  async function onSubmit(values: SavePolicyValues) {
    await save.mutateAsync({
      capability: values.capability,
      body: { candidates: values.candidates, thinking: thinkingToApi(values.thinking) },
    });
    onOpenChange(false);
  }

  const rootError = form.formState.errors.candidates?.root ?? form.formState.errors.candidates;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto overscroll-contain sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit routing policy' : 'Add routing policy'}</DialogTitle>
          <DialogDescription>
            A capability resolves to the highest-priority candidate whose
            requirements hold; higher numbers are tried first. An empty
            requirement list matches anything.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form id="policy-form" className="space-y-5" onSubmit={form.handleSubmit(onSubmit)}>
            <FormField
              control={form.control}
              name="capability"
              label="Capability"
              description="One policy per capability."
              render={(field) =>
                isEdit ? (
                  <Select value={field.value as string} disabled>
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={field.value as string}>
                        {field.value as string}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                ) : (
                  <Select
                    value={field.value as string}
                    onValueChange={(value) => field.onChange(value)}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {capabilityOptions.map((capability) => (
                        <SelectItem key={capability} value={capability}>
                          {capability}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )
              }
            />

            <FormField
              control={form.control}
              name="thinking"
              label="Deliberation"
              description="What applies to a request that specifies nothing. Disable it for agent
                clients: they incur the cost again on every tool round trip, and a deliberating model
                can consume an entire token budget without answering."
              render={(field) => (
                <Select
                  value={(field.value as string) ?? 'default'}
                  onValueChange={(value) => field.onChange(value)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="default">Deployment default</SelectItem>
                    <SelectItem value="on">Deliberate before answering</SelectItem>
                    <SelectItem value="off">Answer directly</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />

            <PolicyCandidatesEditor
              form={form}
              fields={candidates.fields}
              append={candidates.append}
              remove={candidates.remove}
              modelAliases={modelAliases}
              rootError={rootError?.message}
            />

            {save.error ? (
              <p role="alert" className="text-sm text-destructive">
                {describeError(save.error)}
              </p>
            ) : null}
          </form>
        </Form>

        <DialogFooter>
          <DialogClose render={<Button variant="outline" disabled={save.isPending} />}>
            Cancel
          </DialogClose>
          <Button type="submit" form="policy-form" disabled={save.isPending}>
            {save.isPending ? 'Saving...' : isEdit ? 'Save changes' : 'Create policy'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
