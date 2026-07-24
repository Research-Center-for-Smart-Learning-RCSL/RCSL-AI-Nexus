'use client';

/**
 * The one-line form row used across modules: label, control, description and
 * the resolver's error message. Wraps react-hook-form's Controller so a feature
 * never touches field wiring directly (frontend.md section 5).
 */

import type {
  HTMLInputTypeAttribute,
  ReactElement,
  ReactNode,
} from 'react';
import type { Control, FieldPath, FieldValues } from 'react-hook-form';

import { Input } from '@/components/ui/input';
import {
  FormControl,
  FormDescription,
  FormField as RhfFormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';

export type FormFieldProps<
  TFieldValues extends FieldValues,
  TName extends FieldPath<TFieldValues>,
> = {
  control: Control<TFieldValues>;
  name: TName;
  label: ReactNode;
  description?: ReactNode;
  placeholder?: string;
  type?: HTMLInputTypeAttribute;
  autoComplete?: string;
  disabled?: boolean;
  /**
   * Renders something other than a plain input, for example a Select. Receives
   * the field props; must spread them onto a single control element.
   */
  render?: (field: {
    value: unknown;
    onChange: (value: unknown) => void;
    onBlur: () => void;
    name: TName;
    disabled?: boolean;
  }) => ReactElement;
};

export function FormField<
  TFieldValues extends FieldValues,
  TName extends FieldPath<TFieldValues>,
>({
  control,
  name,
  label,
  description,
  placeholder,
  type = 'text',
  autoComplete,
  disabled,
  render,
}: FormFieldProps<TFieldValues, TName>) {
  return (
    <RhfFormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            {render ? (
              render({
                value: field.value,
                onChange: field.onChange,
                onBlur: field.onBlur,
                name,
                disabled: disabled ?? field.disabled,
              })
            ) : (
              <Input
                {...field}
                value={(field.value as string | number | undefined) ?? ''}
                type={type}
                placeholder={placeholder}
                autoComplete={autoComplete}
                disabled={disabled ?? field.disabled}
              />
            )}
          </FormControl>
          {description ? <FormDescription>{description}</FormDescription> : null}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}
