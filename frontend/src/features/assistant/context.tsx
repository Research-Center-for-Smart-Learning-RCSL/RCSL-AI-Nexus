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
 *
 * **Registrations are a stack, not a slot.** Screens genuinely nest: the key
 * table publishes `api_keys.list` and stays mounted while a dialog on top of it
 * publishes `api_keys.create`. With one slot the dialog's cleanup reset the
 * surface to `other` on close, and the table underneath never re-registered —
 * its effect dependencies had not changed — so closing a dialog silently took
 * the assistant's context away from the screen still in front of the operator.
 * The stack restores whatever is beneath, which is what the callers already
 * assumed and said in their comments.
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
  /**
   * Read at send time. Never state; see the module docstring. May return
   * undefined, which is how a screen with no form differs from one whose form
   * is open and empty — a distinction the system prompt makes.
   */
  readDraft?: () => ApiKeyDraft | undefined;
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
  /**
   * Whether the panel is showing.
   *
   * Held here rather than inside the drawer because two things outside it now
   * depend on the answer: the shell header owns the button that opens it, and
   * the shell reserves room for the panel on a wide screen so it stops covering
   * the table the question is about.
   */
  isOpen: boolean;
  setOpen: (open: boolean) => void;
};

const AssistantContext = createContext<AssistantContextValue | null>(null);

const NOTHING = { surface: 'other' as AssistSurface, keyId: undefined, canApply: false };

export function AssistantContextProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<{
    surface: AssistSurface;
    keyId: string | undefined;
    canApply: boolean;
  }>(NOTHING);
  const stack = useRef<AssistantRegistration[]>([]);
  const [isOpen, setOpen] = useState(false);

  const sync = useCallback(() => {
    const top = stack.current.at(-1);
    setActive(
      top === undefined
        ? NOTHING
        : {
            surface: top.surface,
            keyId: top.keyId,
            canApply: top.applyPatch !== undefined,
          },
    );
  }, []);

  const register = useCallback(
    (registration: AssistantRegistration) => {
      stack.current = [...stack.current, registration];
      sync();

      return () => {
        // Removed by identity rather than popped, so unmount order does not
        // have to be the reverse of mount order — which is not something a
        // caller controls, and which React's strict-mode double-invoke breaks
        // on purpose. Whatever remains beneath becomes active again.
        stack.current = stack.current.filter((entry) => entry !== registration);
        sync();
      };
    },
    [sync],
  );

  const value = useMemo<AssistantContextValue>(
    () => ({
      ...active,
      readDraft: () => stack.current.at(-1)?.readDraft?.(),
      applyPatch: (patch) => stack.current.at(-1)?.applyPatch?.(patch),
      register,
      isOpen,
      setOpen,
    }),
    [active, register, isOpen],
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
      // `undefined`, not `{}`, for a screen with no form. An empty object is
      // indistinguishable from a form the operator has opened and not filled,
      // and the backend would then describe an empty key form to the model
      // while it is being asked about the documentation page.
      readDraft: () => latest.current?.readDraft?.(),
      applyPatch: offersApply
        ? (patch) => latest.current?.applyPatch?.(patch)
        : undefined,
    });
  }, [register, surface, keyId, offersApply]);
}
