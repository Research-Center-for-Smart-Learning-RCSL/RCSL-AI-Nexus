export type AuthMode = 'tailnet' | 'local' | 'dev';

export type Role =
  | 'admin'
  | 'tenant_admin'
  | 'operator'
  | 'curator'
  | 'auditor'
  | 'user';

/** Unknown future scopes narrow the UI instead of breaking it. */
export type ScopeName = string;

export type Me = {
  id: string;
  auth_mode: AuthMode;
  login: string;
  display_name: string;
  role: Role;
  scopes?: ScopeName[];
  session_expires_at: string | null;
};

export type SessionStatus =
  | 'loading'
  | 'authenticated'
  | 'unauthenticated'
  | 'error';

export type SessionValue = {
  me: Me | null;
  status: SessionStatus;
  error: Error | null;
  authMode: AuthMode | null;
  can: (scope: ScopeName) => boolean;
  isAdmin: boolean;
  hasSession: boolean;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
};
