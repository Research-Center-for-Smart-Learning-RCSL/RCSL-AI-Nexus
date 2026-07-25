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
import { useCreateModel, useUpdateModel } from '@/features/models/hooks/use-models';

const RUNTIMES = runtimeKindSchema.options;
const CAPABILITIES = capabilitySchema.options;

function defaultsFor(model?: Model): CreateModelInput {
  return {
    alias: model?.alias ?? '',
    ref: model?.ref ?? '',
    runtime: model?.runtime ?? 'ollama',
    node_id: model?.node_id ?? '',
    capabilities: model?.capabilities ?? ['chat'],
    resource_profile: model?.resource_profile ?? {
      memory_gb: 8,
      context_length: 8192,
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
              />
            </div>

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
