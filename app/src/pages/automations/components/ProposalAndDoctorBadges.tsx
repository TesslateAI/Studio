/**
 * Per-row badges showing (a) the number of pending agent proposals
 * waiting for review and (b) whether the doctor is watching this
 * workflow. Both surface the same affordance: hover to learn,
 * click row to act. We fetch /proposals?status=submitted lazily per
 * row — cheap (count-only) and keeps the list-page query light.
 */

import { useEffect, useState } from 'react';
import { Robot } from '@phosphor-icons/react';
import { automationsApi } from '../../../lib/api';

interface Props {
  automationId: string;
  doctorEnabled: boolean;
}

export default function ProposalAndDoctorBadges({ automationId, doctorEnabled }: Props) {
  const [pending, setPending] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    automationsApi
      .listProposals(automationId, 'submitted')
      .then((rows) => {
        if (cancelled) return;
        setPending(Array.isArray(rows) ? rows.length : 0);
      })
      .catch(() => {
        if (!cancelled) setPending(0);
      });
    return () => {
      cancelled = true;
    };
  }, [automationId]);

  if (!pending && !doctorEnabled) return null;

  return (
    <span className="inline-flex items-center gap-1">
      {pending ? (
        <span
          className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 tabular-nums"
          title={`${pending} proposal${pending === 1 ? '' : 's'} awaiting review`}
        >
          {pending}
        </span>
      ) : null}
      {doctorEnabled && (
        <Robot className="w-3.5 h-3.5 text-emerald-400" aria-label="Doctor enabled">
          <title>Self-healing doctor is watching this workflow</title>
        </Robot>
      )}
    </span>
  );
}
