'use client';

import { useState } from 'react';
import { PlusIcon, Trash2Icon } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';

import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { FormField } from '@/components/composed/form-field';
import { ConfirmDialog } from '@/components/composed/confirm-dialog';
import { cn } from '@/lib/utils';
import {
  useCollections,
  useCreateCollection,
  useDeleteCollection,
} from '@/features/knowledge/hooks/use-knowledge';
import {
  createCollectionSchema,
  type Collection,
  type CreateCollectionInput,
} from '@/features/knowledge/schema';

export type CollectionListProps = {
  selectedId: string | undefined;
  onSelect: (id: string | undefined) => void;
};

export function CollectionList({ selectedId, onSelect }: CollectionListProps) {
  const { data: collections, isLoading } = useCollections();
  const remove = useDeleteCollection();
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<Collection | null>(null);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium">Collections</h2>
        <Button size="xs" variant="outline" onClick={() => setCreating(true)}>
          <PlusIcon />
          New
        </Button>
      </div>

      <nav className="space-y-1">
        <button
          type="button"
          onClick={() => onSelect(undefined)}
          className={cn(
            'w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent',
            selectedId === undefined && 'bg-accent font-medium',
          )}
        >
          All documents
        </button>

        {isLoading ? (
          <p className="px-2 py-1.5 text-sm text-muted-foreground">Loading…</p>
        ) : null}

        {collections?.map((collection) => (
          <div key={collection.id} className="group flex items-center gap-1">
            <button
              type="button"
              onClick={() => onSelect(collection.id)}
              className={cn(
                'flex-1 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent',
                selectedId === collection.id && 'bg-accent font-medium',
              )}
            >
              <span className="block truncate">{collection.name}</span>
              <span className="block text-xs text-muted-foreground">
                {collection.document_count}{' '}
                {collection.document_count === 1 ? 'document' : 'documents'}
              </span>
            </button>
            <Button
              variant="ghost"
              size="xs"
              aria-label={`Delete ${collection.name}`}
              className="text-destructive opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
              onClick={() => setDeleting(collection)}
            >
              <Trash2Icon />
            </Button>
          </div>
        ))}

        {collections?.length === 0 ? (
          <p className="px-2 py-1.5 text-sm text-muted-foreground">
            No collections yet.
          </p>
        ) : null}
      </nav>

      <CreateCollectionDialog open={creating} onOpenChange={setCreating} />

      <ConfirmDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={`Delete ${deleting?.name ?? 'this collection'}?`}
        // Said plainly because it is not recoverable: the documents, their
        // stored files and their indexed passages all go.
        description={
          deleting
            ? `Its ${deleting.document_count} document(s), their uploaded files and their indexed passages are deleted with it. This cannot be undone.`
            : ''
        }
        confirmLabel="Delete"
        destructive
        onConfirm={async () => {
          if (deleting) {
            await remove.mutateAsync(deleting.id);
            if (selectedId === deleting.id) onSelect(undefined);
          }
        }}
      />
    </div>
  );
}

function CreateCollectionDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const create = useCreateCollection();
  const form = useForm<CreateCollectionInput>({
    resolver: zodResolver(createCollectionSchema),
    defaultValues: { name: '', description: '' },
  });

  const submit = form.handleSubmit(async (values) => {
    await create.mutateAsync(values);
    form.reset();
    onOpenChange(false);
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New collection</DialogTitle>
          <DialogDescription>
            A named group of documents. Retrieval can be limited to one
            collection, so grouping by project keeps unrelated material out of
            an answer.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
        <form
          onSubmit={(event) => {
            // `void`, so an unhandled rejection cannot escape the handler; the
            // mutation reports its own failure through a toast.
            void submit(event);
          }}
          className="space-y-4"
        >
          <FormField
            control={form.control}
            name="name"
            label="Name"
            placeholder="Papers"
          />
          <FormField
            control={form.control}
            name="description"
            label="Description"
            description="Optional. What this collection holds, for the reader selecting one."
          />

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={form.formState.isSubmitting}>
              Create
            </Button>
          </DialogFooter>
        </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
