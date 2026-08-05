/**
 * The hand-written schemas, checked against the API that actually serves them.
 *
 * This file declares no values anybody imports and ships nothing to the
 * browser. It exists so that `tsc` fails when the backend and the frontend stop
 * agreeing — the drift the ROADMAP has wanted caught since Phase 1, and the
 * shape of more than one defect already recorded in PROGRESS: a field present
 * on one side and absent on the other, discovered in a browser rather than in a
 * build.
 *
 * **Why the zod schemas still exist.** `openapi-typescript` emits types, and
 * types are erased. Every response is still `parse`d at runtime, which is what
 * catches a deployment serving something its own schema does not describe, and
 * what turns a wrong shape into one legible error instead of `undefined`
 * spreading through a component tree. The generated types are the second
 * opinion, not the replacement.
 *
 * **What counts as agreement.** Each declared field must exist on the API type
 * and the two must be *comparable* — one assignable to the other, in either
 * direction. Not equality, because two refinements are deliberate and both are
 * enforced by zod at runtime rather than merely asserted here:
 *
 * - narrowing `string` to a union, where the backend's type is `str` but the
 *   set of values is closed (`role`, `state`, `runtime`);
 * - reading a subset, since a screen need not consume every field a response
 *   carries.
 *
 * What is *not* tolerated is a field that has been renamed or removed, or whose
 * type changed to something unrelated. Those are the ones that reach a user.
 *
 * **Dropping `null` is checked separately, and it is the reason this file found
 * anything.** Assignability alone waves it through — `string` *is* assignable
 * to `string | null` — so a schema declaring `z.string()` against a field the
 * API says may be null looks like one more deliberate narrowing. It is not the
 * same kind of thing. Narrowing `string` to `'admin' | 'user'` says "of the
 * values this could hold, these are the ones the platform emits", and zod
 * enforces it. Dropping `null` says "this is never null" about a field the API
 * declares nullable, and the moment it *is* null the parse throws and the
 * screen shows an error instead of a row. So a nullable API field requires a
 * nullable schema, assignable or not.
 */

import type { components } from '@/lib/generated/admin-api';

import type { ApiKey, IssuedApiKey } from '@/features/api-keys/schema';
import type { DashboardSummary } from '@/features/dashboard/schema';
import type { GatewayInfo } from '@/features/gateway/schema';
import type { HostStatus } from '@/features/host/schema';
import type {
  Collection,
  DocumentPage,
  DocumentText,
  KnowledgeDocument,
  Passage,
} from '@/features/knowledge/schema';
import type { AuditEntry, AuditLogPage } from '@/features/logs/schema';
import type { DownloadJob, Model, Node } from '@/features/models/schema';
import type {
  PurgeOutcome,
  RetentionPolicy,
  RetentionPreview,
} from '@/features/retention/schema';
import type { RoutingPolicy } from '@/features/routing-policies/schema';
import type { Tenant } from '@/features/tenants/schema';
import type { Invitation, RoleCatalogueEntry, User } from '@/features/users/schema';

type Api = components['schemas'];

/**
 * The declared keys that no longer line up, as a union — empty when they all do.
 *
 * `-?` strips optionality before the comparison, so a field the schema marks
 * optional is still required to exist on the API. An optional field that the
 * backend deleted is exactly as broken as a required one; it is just quieter.
 */
type Incompatible<Declared, ApiShape> = {
  [K in keyof Declared]-?: K extends keyof ApiShape
    ? null extends ApiShape[K]
      ? // The API says this may be null, so the schema has to accept null.
        // Checked before assignability because assignability permits exactly
        // the mistake: `string` satisfies `string | null` and then throws on
        // the first null the backend sends.
        null extends Declared[K]
        ? never
        : K
      : Declared[K] extends ApiShape[K]
        ? never
        : ApiShape[K] extends Declared[K]
          ? never
          : K
    : K;
}[keyof Declared];

/**
 * `true` when the two agree, otherwise the offending keys.
 *
 * Resolving to the keys rather than to `false` is the whole ergonomics of this
 * file: the compiler error reads `Type 'true' is not assignable to type
 * '"created_at"'`, which names the field to go and look at. The tuple wrapper
 * stops the conditional distributing over a union of keys, which would collapse
 * a real mismatch to `never` and report agreement.
 */
type Agrees<Declared, ApiShape> = [Incompatible<Declared, ApiShape>] extends [never]
  ? true
  : Incompatible<Declared, ApiShape>;

/* eslint-disable @typescript-eslint/no-unused-vars -- each binding is the assertion */

// --- accounts and access -------------------------------------------------
const _user: Agrees<User, Api['UserResponse']> = true;
const _invitation: Agrees<Invitation, Api['InvitationResponse']> = true;
const _role: Agrees<RoleCatalogueEntry, Api['RoleResponse']> = true;
const _apiKey: Agrees<ApiKey, Api['ApiKeyResponse']> = true;
const _issuedKey: Agrees<IssuedApiKey, Api['IssuedApiKeyResponse']> = true;
const _tenant: Agrees<Tenant, Api['TenantResponse']> = true;

// --- the fleet -----------------------------------------------------------
const _model: Agrees<Model, Api['ModelResponse']> = true;
const _node: Agrees<Node, Api['NodeResponse']> = true;
const _download: Agrees<DownloadJob, Api['DownloadJobResponse']> = true;
const _policy: Agrees<RoutingPolicy, Api['RoutingPolicyResponse']> = true;

// --- what the screens read -----------------------------------------------
const _dashboard: Agrees<DashboardSummary, Api['DashboardResponse']> = true;
const _gateway: Agrees<GatewayInfo, Api['GatewayInfoResponse']> = true;
const _host: Agrees<HostStatus, Api['HostStatusResponse']> = true;
const _auditEntry: Agrees<AuditEntry, Api['AuditEntryResponse']> = true;
const _auditPage: Agrees<AuditLogPage, Api['AuditLogResponse']> = true;

// --- knowledge base ------------------------------------------------------
const _collection: Agrees<Collection, Api['KnowledgeCollectionResponse']> = true;
const _document: Agrees<KnowledgeDocument, Api['KnowledgeDocumentResponse']> = true;
const _documentPage: Agrees<DocumentPage, Api['KnowledgeDocumentPageResponse']> = true;
const _documentText: Agrees<DocumentText, Api['DocumentTextResponse']> = true;
const _passage: Agrees<Passage, Api['RetrievedPassageResponse']> = true;

// --- retention -----------------------------------------------------------
const _retention: Agrees<RetentionPolicy, Api['RetentionPolicyResponse']> = true;
const _retentionPreview: Agrees<RetentionPreview, Api['RetentionPreviewResponse']> = true;
const _purge: Agrees<PurgeOutcome, Api['PurgeOutcomeResponse']> = true;
