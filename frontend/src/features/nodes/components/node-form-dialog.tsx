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
import { Label } from '@/components/ui/label';
import { describeError } from '@/components/composed/error-state';
import { runtimeKindSchema, type RuntimeKind } from '@/features/models/schema';
import {
  createNodeSchema,
  RUNTIME_LABELS,
  type CreateNodeInput,
  type CreateNodeValues,
  type Node,
} from '@/features/nodes/schema';
import { useCreateNode, useUpdateNode } from '@/features/nodes/hooks/use-nodes';

const RUNTIMES = runtimeKindSchema.options;

function defaultsFor(node?: Node): CreateNodeInput {
  return {
    name: node?.name ?? '',
    address: node?.address ?? '',
    total_memory_gb: node?.total_memory_gb ?? 64,
    runtimes: node?.runtimes ?? ['ollama'],
  };
}

export type NodeFormDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Absent for create. */
  node?: Node;
};

export function NodeFormDialog({ open, onOpenChange, node }: NodeFormDialogProps) {
  const isEdit = Boolean(node);
  const create = useCreateNode();
  const update = useUpdateNode(node?.id ?? '');
  const pending = create.isPending || update.isPending;
  const error = create.error ?? update.error;

  const form = useForm<CreateNodeInput, unknown, CreateNodeValues>({
    resolver: zodResolver(createNodeSchema),
    defaultValues: defaultsFor(node),
  });

  async function onSubmit(values: CreateNodeValues) {
    if (isEdit) await update.mutateAsync(values);
    else await create.mutateAsync(values);
    onOpenChange(false);
    form.reset(defaultsFor());
  }

  const selected = form.watch('runtimes');

  function toggleRuntime(runtime: RuntimeKind, checked: boolean) {
    const next = checked
      ? [...selected, runtime]
      : selected.filter((item) => item !== runtime);
    form.setValue('runtimes', next, { shouldValidate: true });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit node' : 'Register a node'}</DialogTitle>
          <DialogDescription>
            The address must be a tailnet address; it is validated server-side
            before it is stored, since the platform makes requests to it. Status
            is observed by probing, not set here.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form
            id="node-form"
            className="space-y-4"
            onSubmit={form.handleSubmit(onSubmit)}
          >
            <FormField
              control={form.control}
              name="name"
              label="Name"
              placeholder="mac-studio-01"
              description="Display name, unique across nodes."
            />
            <FormField
              control={form.control}
              name="address"
              label="Tailnet address"
              placeholder="100.101.102.103"
              description="A 100.x tailnet address or a MagicDNS name that resolves into it."
            />
            <FormField
              control={form.control}
              name="total_memory_gb"
              label="Total memory (GB)"
              type="number"
              description="The figure the memory budget refuses a load against, so it must match the machine."
            />

            <div className="space-y-2">
              <Label>Runtimes</Label>
              <div className="flex flex-wrap gap-3">
                {RUNTIMES.map((runtime) => (
                  <label
                    key={runtime}
                    className="flex items-center gap-1.5 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(runtime)}
                      onChange={(event) =>
                        toggleRuntime(runtime, event.target.checked)
                      }
                    />
                    {RUNTIME_LABELS[runtime]}
                  </label>
                ))}
              </div>
              {form.formState.errors.runtimes ? (
                <p className="text-sm text-destructive">
                  {form.formState.errors.runtimes.message}
                </p>
              ) : null}
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
          <Button type="submit" form="node-form" disabled={pending}>
            {pending ? 'Saving...' : isEdit ? 'Save changes' : 'Register'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
