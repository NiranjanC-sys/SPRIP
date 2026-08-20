import {
  AlertOctagon,
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleDashed,
  CircleDot,
  Clock,
  Eye,
  FileText,
  HelpCircle,
  Hourglass,
  Layers,
  Lock,
  Loader2,
  Pause,
  Search,
  ShieldCheck,
  ShieldQuestion,
  Timer,
  XCircle,
} from 'lucide-react';

import { cn, humanizeEnum } from '@/lib/utils';
import { Badge, type BadgeVariant } from '@/components/ui/badge';

/**
 * Status → icon + colour + label, for every status enum in the domain.
 *
 * plan.md §7.0 forbids colour as the sole carrier of meaning, so a status is
 * always three signals at once: a shape (icon), a hue, and a word. That is also
 * why this is a lookup table rather than a `switch` sprinkled across pages — a
 * status rendered green here and amber there is a correctness bug in a product
 * whose whole job is not overstating certainty.
 *
 * Keys are the raw enum tokens. Several enums share tokens (`ACTIVE`, `DRAFT`,
 * `REJECTED`); where they do, the semantics coincide, so one entry serves all.
 */

type Icon = typeof CheckCircle2;

interface StatusMeta {
  label: string;
  variant: BadgeVariant;
  icon: Icon;
  /** Rendered with a spin animation — an in-flight state, not a resting one. */
  busy?: boolean;
}

const STATUS_META: Readonly<Record<string, StatusMeta>> = {
  /* --- lifecycle / generic ------------------------------------------------ */
  ACTIVE: { label: 'Active', variant: 'positive', icon: CheckCircle2 },
  DRAFT: { label: 'Draft', variant: 'neutral', icon: FileText },
  PENDING: { label: 'Pending', variant: 'info', icon: Clock },
  PENDING_ONBOARDING: { label: 'Pending onboarding', variant: 'info', icon: Hourglass },
  SUSPENDED: { label: 'Suspended', variant: 'warning', icon: Pause },
  ARCHIVED: { label: 'Archived', variant: 'neutral', icon: Layers },
  EXPIRED: { label: 'Expired', variant: 'warning', icon: Timer },
  REVOKED: { label: 'Revoked', variant: 'danger', icon: Ban },
  DISABLED: { label: 'Disabled', variant: 'danger', icon: Ban },
  LOCKED: { label: 'Locked', variant: 'danger', icon: Lock },
  INVITED: { label: 'Invited', variant: 'info', icon: Clock },
  ACCEPTED: { label: 'Accepted', variant: 'positive', icon: CheckCircle2 },
  CANCELLED: { label: 'Cancelled', variant: 'neutral', icon: XCircle },
  COMPLETED: { label: 'Completed', variant: 'positive', icon: CheckCircle2 },
  SUPERSEDED: { label: 'Superseded', variant: 'neutral', icon: Layers },
  SAVED: { label: 'Saved', variant: 'neutral', icon: CheckCircle2 },

  /* --- events ------------------------------------------------------------- */
  PROPOSED: { label: 'Proposed', variant: 'neutral', icon: CircleDashed },
  SCHEDULED: { label: 'Scheduled', variant: 'info', icon: Clock },

  /* --- attendance --------------------------------------------------------- */
  NOT_REGISTERED: { label: 'Not registered', variant: 'neutral', icon: CircleDashed },
  REGISTERED: { label: 'Registered', variant: 'info', icon: CircleDot },
  WAITLISTED: { label: 'Waitlisted', variant: 'warning', icon: Hourglass },
  NO_SHOW: { label: 'No show', variant: 'neutral', icon: XCircle },
  ATTENDED: { label: 'Attended', variant: 'positive', icon: CheckCircle2 },

  /* --- verification sources ----------------------------------------------- */
  BADGE_SCAN: { label: 'Badge scan', variant: 'positive', icon: ShieldCheck },
  SIGN_IN_SHEET: { label: 'Sign-in sheet', variant: 'positive', icon: ShieldCheck },
  WEBINAR_PLATFORM_LOG: { label: 'Platform log', variant: 'positive', icon: ShieldCheck },
  VENDOR_ATTESTATION: { label: 'Vendor attestation', variant: 'warning', icon: ShieldQuestion },
  UNVERIFIED: { label: 'Unverified', variant: 'danger', icon: AlertTriangle },

  /* --- identity resolution ------------------------------------------------ */
  MATCHED: { label: 'Matched', variant: 'positive', icon: CheckCircle2 },
  MANUALLY_MATCHED: { label: 'Manually matched', variant: 'positive', icon: CheckCircle2 },
  AMBIGUOUS: { label: 'Ambiguous', variant: 'warning', icon: HelpCircle },
  UNMATCHED: { label: 'Unmatched', variant: 'warning', icon: AlertTriangle },

  /* --- ingestion ---------------------------------------------------------- */
  CREATED: { label: 'Created', variant: 'neutral', icon: CircleDashed },
  UPLOADED: { label: 'Uploaded', variant: 'info', icon: CheckCircle2 },
  SCANNING: { label: 'Scanning', variant: 'info', icon: Search, busy: true },
  VALIDATING: { label: 'Validating', variant: 'info', icon: Loader2, busy: true },
  CONFORMING: { label: 'Conforming', variant: 'info', icon: Loader2, busy: true },
  PARTIALLY_ACCEPTED: { label: 'Partially accepted', variant: 'warning', icon: AlertTriangle },
  REJECTED: { label: 'Rejected', variant: 'danger', icon: XCircle },
  QUARANTINED: { label: 'Quarantined', variant: 'warning', icon: AlertOctagon },
  ABANDONED: { label: 'Abandoned', variant: 'neutral', icon: Ban },
  FAILED: { label: 'Failed', variant: 'danger', icon: XCircle },

  /* --- issue severity ----------------------------------------------------- */
  ERROR: { label: 'Error', variant: 'danger', icon: XCircle },
  QUARANTINE: { label: 'Quarantine', variant: 'warning', icon: AlertOctagon },
  WARNING: { label: 'Warning', variant: 'warning', icon: AlertTriangle },
  INFO: { label: 'Info', variant: 'info', icon: HelpCircle },

  /* --- workflow / publication --------------------------------------------- */
  DATA_PENDING: { label: 'Data pending', variant: 'neutral', icon: Hourglass },
  DATA_ISSUES: { label: 'Data issues', variant: 'warning', icon: AlertTriangle },
  READY_FOR_ANALYSIS: { label: 'Ready for analysis', variant: 'info', icon: CircleDot },
  ANALYSIS_RUNNING: { label: 'Analysis running', variant: 'info', icon: Loader2, busy: true },
  ANALYSIS_COMPLETE: { label: 'Analysis complete', variant: 'positive', icon: CheckCircle2 },
  UNDER_REVIEW: { label: 'Under review', variant: 'info', icon: Eye },
  APPROVED: { label: 'Approved', variant: 'positive', icon: CheckCircle2 },
  PUBLISHED: { label: 'Published', variant: 'positive', icon: ShieldCheck },
  SUBMITTED: { label: 'Submitted', variant: 'info', icon: Clock },
  CHANGES_REQUESTED: { label: 'Changes requested', variant: 'warning', icon: AlertTriangle },

  /* --- runs --------------------------------------------------------------- */
  QUEUED: { label: 'Queued', variant: 'neutral', icon: Clock },
  RUNNING: { label: 'Running', variant: 'info', icon: Loader2, busy: true },
  SUCCEEDED: { label: 'Succeeded', variant: 'positive', icon: CheckCircle2 },
  DEAD_LETTER: { label: 'Dead letter', variant: 'danger', icon: AlertOctagon },

  /* --- model lifecycle ---------------------------------------------------- */
  TRAINING: { label: 'Training', variant: 'info', icon: Loader2, busy: true },
  CHALLENGER: { label: 'Challenger', variant: 'info', icon: CircleDot },
  PENDING_APPROVAL: { label: 'Pending approval', variant: 'warning', icon: Clock },
  RETIRED: { label: 'Retired', variant: 'neutral', icon: Layers },

  /* --- evidence ----------------------------------------------------------- */
  ESTIMATED: { label: 'Estimated', variant: 'positive', icon: CheckCircle2 },
  NOT_RELIABLY_ESTIMABLE: { label: 'Not reliably estimable', variant: 'warning', icon: AlertTriangle },

  /* --- forecast ----------------------------------------------------------- */
  MODEL: { label: 'Model', variant: 'positive', icon: CheckCircle2 },
  POOLED: { label: 'Pooled', variant: 'warning', icon: Layers },
  OUT_OF_SUPPORT: { label: 'Out of support', variant: 'danger', icon: AlertOctagon },

  /* --- optimizer ---------------------------------------------------------- */
  OPTIMAL: { label: 'Optimal', variant: 'positive', icon: CheckCircle2 },
  FEASIBLE_SUBOPTIMAL: { label: 'Feasible (suboptimal)', variant: 'warning', icon: AlertTriangle },
  INFEASIBLE: { label: 'Infeasible', variant: 'danger', icon: XCircle },
  UNBOUNDED: { label: 'Unbounded', variant: 'danger', icon: AlertOctagon },
  TIME_LIMIT: { label: 'Time limit reached', variant: 'warning', icon: Timer },

  /* --- audit -------------------------------------------------------------- */
  SUCCESS: { label: 'Success', variant: 'positive', icon: CheckCircle2 },
  FAILURE: { label: 'Failure', variant: 'danger', icon: XCircle },
  PERMISSION_DENIED: { label: 'Permission denied', variant: 'danger', icon: Lock },
};

export interface StatusBadgeProps {
  /** Any status enum token. Unknown tokens degrade to a humanised neutral badge. */
  value: string | null | undefined;
  size?: 'sm' | 'md';
  className?: string;
  /** Suppresses the icon. Only for very dense table cells where a column header already says "Status". */
  iconOnly?: false;
}

export function StatusBadge({ value, size = 'sm', className }: StatusBadgeProps) {
  if (!value) {
    return (
      <Badge variant="neutral" size={size} className={className}>
        <CircleDashed aria-hidden="true" />
        Unknown
      </Badge>
    );
  }

  // An unmapped token still renders something legible rather than blowing up —
  // the API can add an enum member before the frontend ships its label.
  const meta = STATUS_META[value] ?? {
    label: humanizeEnum(value),
    variant: 'neutral' as const,
    icon: CircleDashed,
  };
  const Icon = meta.icon;

  return (
    <Badge variant={meta.variant} size={size} className={className}>
      <Icon
        aria-hidden="true"
        className={cn(meta.busy && 'animate-spin motion-reduce:animate-none')}
      />
      {meta.label}
    </Badge>
  );
}

/** Label lookup for places that need the word without the badge (exports, tooltips). */
export function statusLabel(value: string | null | undefined): string {
  if (!value) return 'Unknown';
  return STATUS_META[value]?.label ?? humanizeEnum(value);
}
