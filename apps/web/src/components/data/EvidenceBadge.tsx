'use client';

import { CircleSlash, ShieldAlert, ShieldCheck, ShieldQuestion } from 'lucide-react';

import { EvidenceGrade } from '@/lib/api/enums';
import { humanizeEnum } from '@/lib/utils';
import { Badge, type BadgeVariant } from '@/components/ui/badge';
import { Tooltip } from '@/components/ui/tooltip';

/**
 * Evidence grade badge.
 *
 * plan.md §12.4: the grade is *derived from hard gates*, not a learned
 * confidence score. The tooltip says so, because the single most likely
 * misreading of this product is treating STRONG as a model output rather than
 * as "this analysis passed the following pre-registered checks".
 */

interface GradeMeta {
  label: string;
  variant: BadgeVariant;
  icon: typeof ShieldCheck;
  explanation: string;
}

const GRADE_META: Readonly<Record<EvidenceGrade, GradeMeta>> = {
  [EvidenceGrade.STRONG]: {
    label: 'Strong',
    variant: 'positive',
    icon: ShieldCheck,
    explanation:
      'All hard gates passed, including a valid control cohort, covariate balance, parallel pre-trends and a stable sensitivity suite. Suitable for external reporting.',
  },
  [EvidenceGrade.MODERATE]: {
    label: 'Moderate',
    variant: 'info',
    icon: ShieldCheck,
    explanation:
      'The core gates passed but at least one robustness check was weaker than the Strong threshold. Usable for internal decisions; state the caveat when quoting it.',
  },
  [EvidenceGrade.DIRECTIONAL]: {
    label: 'Directional',
    variant: 'warning',
    icon: ShieldAlert,
    explanation:
      'Sample size or control quality limits the estimate to a direction of effect. Do not quote the magnitude, and do not use it as a basis for reallocating budget on its own.',
  },
  [EvidenceGrade.NOT_ESTIMABLE]: {
    label: 'Not estimable',
    variant: 'neutral',
    icon: CircleSlash,
    explanation:
      'One or more hard gates failed, so no causal estimate is reported. This is a refusal to guess, not a result of zero.',
  },
};

export interface EvidenceBadgeProps {
  grade: EvidenceGrade | string | null | undefined;
  size?: 'sm' | 'md';
  /** Adds "Evidence:" before the grade. Use on standalone placements. */
  prefix?: boolean;
  className?: string;
  /** Extra sentence appended to the tooltip — e.g. the capping control strategy. */
  note?: string | null;
}

export function EvidenceBadge({ grade, size = 'sm', prefix, className, note }: EvidenceBadgeProps) {
  if (!grade) {
    return (
      <Badge variant="neutral" size={size} className={className}>
        <ShieldQuestion aria-hidden="true" />
        No grade
      </Badge>
    );
  }

  const meta = GRADE_META[grade as EvidenceGrade];
  if (!meta) {
    return (
      <Badge variant="neutral" size={size} className={className}>
        <ShieldQuestion aria-hidden="true" />
        {humanizeEnum(String(grade))}
      </Badge>
    );
  }

  const Icon = meta.icon;

  return (
    <Tooltip
      content={
        <div className="flex flex-col gap-1.5">
          <p className="font-semibold text-text">Evidence: {meta.label}</p>
          <p>{meta.explanation}</p>
          {note ? <p className="text-text-subtle">{note}</p> : null}
        </div>
      }
    >
      <span>
        <Badge variant={meta.variant} size={size} className={className}>
          <Icon aria-hidden="true" />
          {prefix ? `Evidence: ${meta.label}` : meta.label}
        </Badge>
      </span>
    </Tooltip>
  );
}

export function evidenceGradeLabel(grade: EvidenceGrade | string | null | undefined): string {
  if (!grade) return 'No grade';
  return GRADE_META[grade as EvidenceGrade]?.label ?? humanizeEnum(String(grade));
}
