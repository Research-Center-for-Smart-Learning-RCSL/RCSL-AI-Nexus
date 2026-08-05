'use client';

import { useForm, useFieldArray } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { PlusIcon, Trash2Icon } from 'lucide-react';

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
import { Label } from '@/components/ui/label';
import { describeError } from '@/components/composed/error-state';
import type { Capability } from '@/features/models/schema';
import {
  MODEL_STATES,
  NODE_STATUSES,
  savePolicyFormSchema,
  thinkingToApi,
  thinkingToForm,
  type RoutingPolicy,
  type SavePolicyInput,
  type SavePolicyValues,
} from '@/features/routing-policies/schema';
import { useSaveRoutingPolicy } from '@/features/routing-policies/hooks/use-routing-policies';

function emptyCandidate(): SavePolicyInput['candidates'][number] {
  return {
    model_alias: '',
    priority: 100,
    require: { node_status: [], model_state: [], min_free_memory_gb: '' },
  };
}

function defaultsFor(policy: RoutingPolicy | undefined, capability: Capability): SavePolicyInput {
  if (!policy) {
    return { capability, candidates: [emptyCandidate()], thinking: 'default' };
  }
  return {
    capability: policy.capability,
    thinking: thinkingToForm(policy.thinking),
    candidates: policy.candidates.map((candidate) => ({
      model_alias: candidate.model_alias,
      priority: candidate.priority,
      require: {
        node_status: [...candidate.require.node_status],
        model_state: [...candidate.require.model_state],
        // The number input is backed by a string; null means "no floor".
        min_free_memory_gb:
          candidate.require.min_free_memory_gb === null
            ? ''
            : String(candidate.require.min_free_memory_gb),
      },
    })),
  };
}

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
    defaultValues: defaultsFor(policy, initialCapability),
  });

  const candidates = useFieldArray({ control: form.control, name: 'candidates' });

  async function onSubmit(values: SavePolicyValues) {
    await save.mutateAsync({
      capability: values.capability,
      body: { candidates: values.candidates, thinking: thinkingToApi(values.thinking) },
    });
    onOpenChange(false);
  }

  function toggleRequirement(
    index: number,
    key: 'node_status' | 'model_state',
    current: string[],
    value: string,
    checked: boolean,
  ) {
    const next = checked ? [...current, value] : current.filter((item) => item !== value);
    // `as never` at the value boundary: the field-array path is a union of two
    // array element types, which RHF's setValue cannot narrow from `key`.
    form.setValue(`candidates.${index}.require.${key}`, next as never, {
      shouldValidate: true,
    });
  }

  const rootError = form.formState.errors.candidates?.root ?? form.formState.errors.candidates;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
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
              description="What a request that says nothing about it gets. Turn it off for agent
                clients: they pay the cost again on every tool round trip, and a thinking model can
                spend a whole token budget without answering."
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
                    <SelectItem value="on">Let the model think</SelectItem>
                    <SelectItem value="off">Answer directly</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />

            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <Label>Candidates</Label>
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  onClick={() => candidates.append(emptyCandidate())}
                >
                  <PlusIcon />
                  Add candidate
                </Button>
              </div>

              {rootError?.message ? (
                <p className="text-sm text-destructive">{rootError.message}</p>
              ) : null}

              {candidates.fields.map((field, index) => {
                const nodeStatus =
                  form.watch(`candidates.${index}.require.node_status`) ?? [];
                const modelState =
                  form.watch(`candidates.${index}.require.model_state`) ?? [];
                return (
                  <div key={field.id} className="space-y-3 rounded-lg ring-1 ring-foreground/10 p-3">
                    <div className="flex items-start gap-3">
                      <div className="flex-1">
                        <FormField
                          control={form.control}
                          name={`candidates.${index}.model_alias`}
                          label="Model alias"
                          placeholder={modelAliases.length ? undefined : 'qwen-coder'}
                          description="Binds to a model's alias, not its id."
                          render={
                            modelAliases.length
                              ? (aliasField) => (
                                  <Select
                                    value={aliasField.value as string}
                                    onValueChange={(value) => aliasField.onChange(value)}
                                  >
                                    <SelectTrigger className="w-full">
                                      <SelectValue placeholder="Choose an alias" />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {modelAliases.map((alias) => (
                                        <SelectItem key={alias} value={alias}>
                                          {alias}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                )
                              : undefined
                          }
                        />
                      </div>
                      <div className="w-28">
                        <FormField
                          control={form.control}
                          name={`candidates.${index}.priority`}
                          label="Priority"
                          type="number"
                        />
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Remove candidate"
                        className="mt-6 text-destructive"
                        disabled={candidates.fields.length === 1}
                        onClick={() => candidates.remove(index)}
                      >
                        <Trash2Icon />
                      </Button>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">
                          Required node status
                        </Label>
                        <div className="flex flex-wrap gap-3">
                          {NODE_STATUSES.map((status) => (
                            <label key={status} className="flex items-center gap-1.5 text-sm">
                              <input
                                type="checkbox"
                                checked={nodeStatus.includes(status)}
                                onChange={(event) =>
                                  toggleRequirement(
                                    index,
                                    'node_status',
                                    nodeStatus,
                                    status,
                                    event.target.checked,
                                  )
                                }
                              />
                              {status}
                            </label>
                          ))}
                        </div>
                      </div>

                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">
                          Required model state
                        </Label>
                        <div className="flex flex-wrap gap-3">
                          {MODEL_STATES.map((state) => (
                            <label key={state} className="flex items-center gap-1.5 text-sm">
                              <input
                                type="checkbox"
                                checked={modelState.includes(state)}
                                onChange={(event) =>
                                  toggleRequirement(
                                    index,
                                    'model_state',
                                    modelState,
                                    state,
                                    event.target.checked,
                                  )
                                }
                              />
                              {state}
                            </label>
                          ))}
                        </div>
                      </div>
                    </div>

                    <div className="sm:w-1/2">
                      <FormField
                        control={form.control}
                        name={`candidates.${index}.require.min_free_memory_gb`}
                        label="Minimum free memory (GB)"
                        type="number"
                        description="Optional. Blank means no floor."
                      />
                    </div>
                  </div>
                );
              })}
            </div>

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
