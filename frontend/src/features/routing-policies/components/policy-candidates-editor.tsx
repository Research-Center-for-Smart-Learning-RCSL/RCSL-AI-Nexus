'use client';

import type {
  FieldArrayWithId,
  UseFormReturn,
} from 'react-hook-form';
import { PlusIcon, Trash2Icon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { FormField } from '@/components/composed/form-field';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type {
  SavePolicyInput,
  SavePolicyValues,
} from '@/features/routing-policies/schema';

import { emptyCandidate } from './policy-form-defaults';
import { PolicyRequirementsEditor } from './policy-requirements-editor';

type PolicyCandidatesEditorProps = {
  form: UseFormReturn<SavePolicyInput, unknown, SavePolicyValues>;
  fields: FieldArrayWithId<SavePolicyInput, 'candidates', 'id'>[];
  append: (candidate: SavePolicyInput['candidates'][number]) => void;
  remove: (index: number) => void;
  modelAliases: string[];
  rootError?: string;
};

export function PolicyCandidatesEditor({
  form,
  fields,
  append,
  remove,
  modelAliases,
  rootError,
}: PolicyCandidatesEditorProps) {
  function toggleRequirement(
    index: number,
    key: 'node_status' | 'model_state',
    current: string[],
    value: string,
    checked: boolean,
  ) {
    const next = checked
      ? [...current, value]
      : current.filter((item) => item !== value);
    form.setValue(`candidates.${index}.require.${key}`, next as never, {
      shouldValidate: true,
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Label>Candidates</Label>
        <Button
          type="button"
          variant="outline"
          size="xs"
          onClick={() => append(emptyCandidate())}
        >
          <PlusIcon />
          Add candidate
        </Button>
      </div>
      {rootError ? <p className="text-sm text-destructive">{rootError}</p> : null}
      {fields.map((field, index) => {
        const nodeStatus =
          form.watch(`candidates.${index}.require.node_status`) ?? [];
        const modelState =
          form.watch(`candidates.${index}.require.model_state`) ?? [];
        return (
          <div
            key={field.id}
            className="space-y-3 rounded-lg p-3 ring-1 ring-foreground/10"
          >
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
                disabled={fields.length === 1}
                onClick={() => remove(index)}
              >
                <Trash2Icon />
              </Button>
            </div>
            <PolicyRequirementsEditor
              nodeStatus={nodeStatus}
              modelState={modelState}
              onToggle={(key, current, value, checked) =>
                toggleRequirement(index, key, current, value, checked)
              }
            />
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
  );
}
