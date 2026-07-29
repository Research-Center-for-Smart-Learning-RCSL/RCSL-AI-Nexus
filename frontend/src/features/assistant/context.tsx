'use client';

/**
 * What the assistant is allowed to know about the screen behind it.
 *
 * A drawer that follows the operator around is only useful if it can see what
 * they are looking at, and only safe if what it can see is enumerated. So this
 * is a registry with a typed shape rather than a channel: a screen publishes a
 * surface name, optionally a form draft, and optionally a way to apply a
 * proposal back. Nothing else fits through it.
 *
 * The plaintext of a freshly issued key is the thing that must never travel
 * here, and it is also the thing the create dialog has in scope at the exact
 * moment it publishes. `ApiKeyDraft` has no field for it, so the omission is
 * enforced by the compiler rather than by whoever edits that dialog next.
 *
 * **The draft lives in a ref, not in state.** It changes on every keystroke,
 * and putting it in context state would re-render every consumer of this
 * provider — including the drawer, mid-stream — for a value nothing reads until
 * a message is sent. The surface does live in state: it changes only when a
 * dialog opens or a route changes, and the drawer's header reads it.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import type { ApiKeyDraft, AssistSurface } from '@/features/assistant/schema';

/** Values a proposal can be applied as; see `proposalToFormPatch`. */
export type FormPatch = Record<string, string | string[]>;

export type AssistantRegistration = {
  surface: AssistSurface;
  /** Which key is being edited, on `api_keys.edit`. */
  keyId?: string;
  /** Read at send time. Never state; see the module docstring. */
  readDraft?: () => ApiKeyDraft;
  /** Applies an accepted proposal to the live form. */
  applyPatch?: (patch: FormPatch) => void;
};

type AssistantContextValue = {
  surface: AssistSurface;
  keyId?: string;
  /** True when the screen offered a way to apply a proposal. */
  canApply: boolean;
  readDraft: () => ApiKeyDraft | undefined;
  applyPatch: (patch: FormPatch) => void;
  register: (registration: AssistantRegistration) => () => void;
};

const AssistantContext = createContext<AssistantContextValue | null>(null);

export function AssistantContextProvider({ children }: { children: ReactNode }) {
  const [surface, setSurface] = useState<AssistSurface>('other');
  const [keyId, setKeyId] = useState<string | undefined>(undefined);
  const [canApply, setCanApply] = useState(false);
  const current = useRef<AssistantRegistration | null>(null);

  const register = useCallback((registration: AssistantRegistration) => {
    current.current = registration;
    setSurface(registration.surface);
    setKeyId(registration.keyId);
    setCanApply(registration.applyPatch !== undefined);

    return () => {
      // Only if this registration is still the live one. A dialog closing after
      // a newer screen has registered would otherwise reset the surface to
      // `other` and take the assistant's context away from the screen that now
      // owns it — unmount order is not something the caller controls.
      if (current.current !== registration) return;
      current.current = null;
      setSurface('other');
      setKeyId(undefined);
      setCanApply(false);
    };
  }, []);

  const value = useMemo<AssistantContextValue>(
    () => ({
      surface,
      keyId,
      canApply,
      readDraft: () => current.current?.readDraft?.(),
      applyPatch: (patch) => current.current?.applyPatch?.(patch),
      register,
    }),
    [surface, keyId, canApply, register],
  );

  return (
    <AssistantContext.Provider value={value}>
      {children}
    </AssistantContext.Provider>
  );
}

export function useAssistantContext(): AssistantContextValue {
  const value = useContext(AssistantContext);
  if (value === null) {
    throw new Error('useAssistantContext must be used inside AssistantContextProvider');
  }
  return value;
}

/**
 * Publishes a screen to the assistant for as long as the component is mounted.
 *
 * `registration` is read through a ref, so a caller need not memoise the
 * callbacks it passes — which they would forget to do, and the symptom would be
 * a re-registration on every keystroke. The effect re-runs only when the
 * identity of the screen changes.
 */
export function useAssistantSurface(
  registration: AssistantRegistration | null,
): void {
  const { register } = useAssistantContext();
  const latest = useRef(registration);
  latest.current = registration;

  const surface = registration?.surface ?? null;
  const keyId = registration?.keyId;
  // Whether the screen offers one, not the callback itself. Forwarding an
  // unconditional wrapper would make every screen look applicable, and the
  // drawer would offer an Apply button that quietly did nothing.
  const offersApply = registration?.applyPatch !== undefined;

  useEffect(() => {
    // `null` means "not right now" and is not the same as registering `other`.
    // A closed dialog that registered `other` would overwrite the surface its
    // own page had published, so the list screen would lose its context every
    // time a dialog was dismissed.
    if (surface === null) return;

    return register({
      surface,
      keyId,
      readDraft: () => latest.current?.readDraft?.() ?? {},
      applyPatch: offersApply
        ? (patch) => latest.current?.applyPatch?.(patch)
        : undefined,
    });
  }, [register, surface, keyId, offersApply]);
}
