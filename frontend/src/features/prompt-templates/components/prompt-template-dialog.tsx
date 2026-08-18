'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Form } from '@/components/ui/form';
import { FormField } from '@/components/composed/form-field';
import { describeError } from '@/components/composed/error-state';
import {
  useCreatePromptTemplate,
  useUpdatePromptTemplate,
} from '@/features/prompt-templates/hooks/use-prompt-templates';
import {
  MAX_SYSTEM_PROMPT_CHARS,
  promptTemplateFormSchema,
  type PromptTemplate,
  type PromptTemplateFormValues,
} from '@/features/prompt-templates/schema';

/**
 * One dialog for both creating and editing, because the fields are identical
 * and the only difference is which mutation runs. Mounted only while a
 * template is selected (or `create` is open), so the form defaults and the
 * `useUpdatePromptTemplate(id)` hook both belong to that row — keeping it
 * mounted and swapping the prop leaves both pointing at whoever was edited
 * first, which is the bug the users table carries a comment about.
 */
export function PromptTemplateDialog({
  template,
  onClose,
}: {
  template: PromptTemplate | null;
  onClose: () => void;
}) {
  const create = useCreatePromptTemplate();
  const update = useUpdatePromptTemplate(template?.id ?? '');
  const editing = template !== null;
  const mutation = editing ? update : create;

  const form = useForm<PromptTemplateFormValues>({
    resolver: zodResolver(promptTemplateFormSchema),
    defaultValues: {
      name: template?.name ?? '',
      description: template?.description ?? '',
      system_prompt: template?.system_prompt ?? '',
    },
  });

  const used = form.watch('system_prompt')?.length ?? 0;

  async function onSubmit(values: PromptTemplateFormValues) {
    try {
      await mutation.mutateAsync(values);
      onClose();
    } catch {
      // Surfaced through mutation.error below. Swallowed so a 409 on a
      // duplicate name does not escape the submit handler as an unhandled
      // rejection.
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{editing ? 'Edit template' : 'New prompt template'}</DialogTitle>
          <DialogDescription>
            The system prompt is placed at the front of the conversation, ahead
            of any system message the caller sends. There is no variable
            substitution: what a caller chooses is which template, not what it
            says.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form
            id="prompt-template-form"
            onSubmit={form.handleSubmit(onSubmit)}
            className="space-y-4"
          >
            <FormField
              control={form.control}
              name="name"
              label="Name"
              placeholder="code-review"
              description={<>What a caller writes in <code>prompt_template</code>. Unique within this tenant.</>}
            />
            <FormField
              control={form.control}
              name="description"
              label="Description"
              placeholder="Terse reviews, no praise"
              description="For whoever is choosing one. Never sent to a model."
            />
            <FormField
              control={form.control}
              name="system_prompt"
              label="System prompt"
              description={`Sent verbatim. ${used} of ${MAX_SYSTEM_PROMPT_CHARS} characters.`}
              render={(field) => (
                <textarea
                  id="prompt-template-system-prompt"
                  value={(field.value as string) ?? ''}
                  onChange={(event) => field.onChange(event.target.value)}
                  onBlur={field.onBlur}
                  rows={12}
                  placeholder="You are reviewing code. Be terse. Name the file and line."
                  className="w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 font-mono text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                />
              )}
            />

            {mutation.error ? (
              <p role="alert" className="text-sm text-destructive">
                {describeError(mutation.error)}
              </p>
            ) : null}
          </form>
        </Form>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="prompt-template-form" disabled={mutation.isPending}>
            {editing ? 'Save' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
