'use client';

import { useForm } from 'react-hook-form';
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
import { Label } from '@/components/ui/label';
import { describeError } from '@/components/composed/error-state';
import {
  capabilitySchema,
  createModelSchema,
  runtimeKindSchema,
  RUNTIME_LABELS,
  type Capability,
  type CreateModelInput,
  type CreateModelValues,
  type Model,
} from '@/features/models/schema';
import {
  useCreateModel,
  useModelReference,
  useUpdateModel,
} from '@/features/models/hooks/use-models';

const RUNTIMES = runtimeKindSchema.options;
const CAPABILITIES = capabilitySchema.options;

export function defaultsFor(model?: Model): CreateModelInput {
  return {
    alias: model?.alias ?? '',
    ref: model?.ref ?? '',
    runtime: model?.runtime ?? 'ollama',
    node_id: model?.node_id ?? '',
    capabilities: model?.capabilities ?? ['chat'],
    // Blank on create, and that is the change of 2026-09-07. These were 8 and
    // 8192, which look like values somebody chose and are values nobody chose:
    // both feed guardrails that fail quietly and late. `memory_gb` is what
    // `MemoryBudgetService` checks on a first load, before any observation
    // exists, so understating it admits a load that evicts everything — the
    // 2026-08-07 shape. And 8192 is the figure `qwen7b` carried, which put the
    // per-model truncation guard at 4096 and served `assist` from a cut prompt
    // until somebody noticed. Both fields are `.positive()`, so blank blocks
    // the submit and asks rather than guessing.
    resource_profile: model?.resource_profile ?? {
      memory_gb: undefined as unknown as number,
      context_length: undefined as unknown as number,
    },
  };
}

export type ModelFormDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Absent for create. */
  model?: Model;
  /** Nodes to choose from, managed under `features/nodes`. */
  nodes?: { id: string; name: string }[];
};

export function ModelFormDialog({
  open,
  onOpenChange,
  model,
  nodes = [],
}: ModelFormDialogProps) {
  const isEdit = Boolean(model);
  const create = useCreateModel();
  const update = useUpdateModel(model?.id ?? '');
  const pending = create.isPending || update.isPending;
  const error = create.error ?? update.error;

  const form = useForm<CreateModelInput, unknown, CreateModelValues>({
    resolver: zodResolver(createModelSchema),
    defaultValues: defaultsFor(model),
  });

  async function onSubmit(values: CreateModelValues) {
    if (isEdit) await update.mutateAsync(values);
    else await create.mutateAsync(values);
    onOpenChange(false);
    form.reset(defaultsFor());
  }

  const selected = form.watch('capabilities');

  // What the host's own weights say, looked up from the reference as it is
  // typed. Offered rather than written: an operator registering a model below
  // its maximum is the ordinary deliberate choice — four of this deployment's
  // six rows do it — so this suggests and the field stays theirs. Registering
  // *above* it is the defect, and `ManageModels.load` warns about that at the
  // moment it would matter.
  const ref = form.watch('ref');
  const { data: reference, isFetching, isError } = useModelReference(ref);
  const declared = reference?.declared_context_length ?? null;

  // Four states reach here and only one of them is "this host has no weights
  // for that name". Saying so while the answer is still in flight is how the
  // Edit dialog would have told an operator that a model it is currently
  // serving does not exist here, and saying it after a failed request would
  // have made that claim permanent for the session — `retry: false` means
  // nothing comes back to correct it. A field that asserts something false
  // about the deployment is worse than one that says nothing.
  const contextHelp = (() => {
    if (declared !== null) {
      return `These weights declare ${declared.toLocaleString()}. Registering below it is fine; above it, the runtime truncates without saying so.`;
    }
    if (ref.trim().length <= 2) return 'What the model can hold.';
    if (isFetching) return 'What the model can hold. Checking what these weights declare…';
    if (isError) return 'What the model can hold. This host could not be asked what they declare.';
    return 'What the model can hold. This host holds no readable weights for that reference.';
  })();

  function toggleCapability(capability: Capability, checked: boolean) {
    const next = checked
      ? [...selected, capability]
      : selected.filter((item) => item !== capability);
    form.setValue('capabilities', next, { shouldValidate: true });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit model' : 'Register a model'}</DialogTitle>
          <DialogDescription>
            The alias is what routing policies bind to; the reference is what is
            passed to the runtime adapter.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form
            id="model-form"
            className="space-y-4"
            onSubmit={form.handleSubmit(onSubmit)}
          >
            <FormField
              control={form.control}
              name="alias"
              label="Alias"
              placeholder="qwen-coder"
              description="Globally unique. Routing policies reference this."
            />
            <FormField
              control={form.control}
              name="ref"
              label="Runtime reference"
              placeholder="qwen2.5-coder:32b"
              description="Unique per runtime and node."
            />
            <FormField
              control={form.control}
              name="runtime"
              label="Runtime"
              render={(field) => (
                <Select
                  value={field.value as string}
                  onValueChange={(value) => field.onChange(value)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {RUNTIMES.map((runtime) => (
                      <SelectItem key={runtime} value={runtime}>
                        {RUNTIME_LABELS[runtime]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            <FormField
              control={form.control}
              name="node_id"
              label="Node"
              placeholder={nodes.length ? undefined : 'Node identifier'}
              render={
                nodes.length
                  ? (field) => (
                      <Select
                        value={field.value as string}
                        onValueChange={(value) => field.onChange(value)}
                      >
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {nodes.map((node) => (
                            <SelectItem key={node.id} value={node.id}>
                              {node.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )
                  : undefined
              }
            />

            <div className="space-y-2">
              <Label>Capabilities</Label>
              <div className="flex flex-wrap gap-3">
                {CAPABILITIES.map((capability) => (
                  <label
                    key={capability}
                    className="flex items-center gap-1.5 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(capability)}
                      onChange={(event) =>
                        toggleCapability(capability, event.target.checked)
                      }
                    />
                    {capability}
                  </label>
                ))}
              </div>
              {form.formState.errors.capabilities ? (
                <p className="text-sm text-destructive">
                  {form.formState.errors.capabilities.message}
                </p>
              ) : null}
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="resource_profile.memory_gb"
                label="Memory (GB)"
                type="number"
                description="Checked against the node budget before a load."
              />
              <FormField
                control={form.control}
                name="resource_profile.context_length"
                label="Context length"
                type="number"
                description={contextHelp}
              />
            </div>
            {declared !== null ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="self-start"
                onClick={() =>
                  form.setValue('resource_profile.context_length', declared, {
                    shouldValidate: true,
                    shouldDirty: true,
                  })
                }
              >
                Use {declared.toLocaleString()}
              </Button>
            ) : null}

            {error ? (
              <p role="alert" className="text-sm text-destructive">
                {describeError(error)}
              </p>
            ) : null}
          </form>
        </Form>

        <DialogFooter>
          <DialogClose render={<Button variant="outline" disabled={pending} />}>
            Cancel
          </DialogClose>
          <Button type="submit" form="model-form" disabled={pending}>
            {pending ? 'Saving...' : isEdit ? 'Save changes' : 'Register'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
