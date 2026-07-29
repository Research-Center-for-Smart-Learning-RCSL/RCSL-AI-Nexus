import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

/** Compute node status, ARCHITECTURE.md section 2.1. */
export type NodeStatus = 'online' | 'offline' | 'degraded';

/** Model lifecycle state, ARCHITECTURE.md section 2.2. */
export type ModelState =
  | 'not_downloaded'
  | 'downloading'
  | 'downloaded'
  | 'loading'
  | 'loaded'
  | 'unloading'
  | 'error';

/** Knowledge base ingestion lifecycle, domain/entities/knowledge.py. */
export type DocumentStatus =
  | 'uploaded'
  | 'extracting'
  | 'extracted'
  | 'indexing'
  | 'indexed';

export type StatusValue =
  | NodeStatus
  | ModelState
  | DocumentStatus
  | 'active'
  | 'revoked'
  | 'expired';

type Descriptor = {
  label: string;
  variant: 'default' | 'secondary' | 'destructive' | 'outline';
  /** Rendered as a small leading dot; colour is the only thing that varies. */
  dot: string;
};

const DESCRIPTORS: Record<StatusValue, Descriptor> = {
  online: { label: 'Online', variant: 'secondary', dot: 'bg-emerald-500' },
  offline: { label: 'Offline', variant: 'outline', dot: 'bg-muted-foreground' },
  degraded: { label: 'Degraded', variant: 'secondary', dot: 'bg-amber-500' },

  not_downloaded: {
    label: 'Not downloaded',
    variant: 'outline',
    dot: 'bg-muted-foreground',
  },
  downloading: { label: 'Downloading', variant: 'secondary', dot: 'bg-sky-500' },
  downloaded: { label: 'Downloaded', variant: 'outline', dot: 'bg-sky-500' },
  loading: { label: 'Loading', variant: 'secondary', dot: 'bg-amber-500' },
  loaded: { label: 'Loaded', variant: 'secondary', dot: 'bg-emerald-500' },
  unloading: { label: 'Unloading', variant: 'secondary', dot: 'bg-amber-500' },
  error: { label: 'Error', variant: 'destructive', dot: 'bg-destructive' },

  // `error` is shared with the model lifecycle above rather than duplicated:
  // it means the same thing to an operator and reads the same either way.
  uploaded: { label: 'Uploaded', variant: 'outline', dot: 'bg-muted-foreground' },
  extracting: { label: 'Extracting', variant: 'secondary', dot: 'bg-sky-500' },
  extracted: { label: 'Extracted', variant: 'outline', dot: 'bg-sky-500' },
  indexing: { label: 'Indexing', variant: 'secondary', dot: 'bg-amber-500' },
  indexed: { label: 'Indexed', variant: 'secondary', dot: 'bg-emerald-500' },

  active: { label: 'Active', variant: 'secondary', dot: 'bg-emerald-500' },
  revoked: { label: 'Revoked', variant: 'destructive', dot: 'bg-destructive' },
  expired: { label: 'Expired', variant: 'outline', dot: 'bg-muted-foreground' },
};

export type StatusBadgeProps = {
  status: StatusValue;
  /** Overrides the default copy, for example to append a progress percentage. */
  label?: string;
  className?: string;
};

export function StatusBadge({ status, label, className }: StatusBadgeProps) {
  const descriptor = DESCRIPTORS[status] ?? {
    label: status,
    variant: 'outline' as const,
    dot: 'bg-muted-foreground',
  };

  return (
    <Badge variant={descriptor.variant} className={cn('gap-1.5', className)}>
      <span className={cn('size-1.5 rounded-full', descriptor.dot)} />
      {label ?? descriptor.label}
    </Badge>
  );
}
