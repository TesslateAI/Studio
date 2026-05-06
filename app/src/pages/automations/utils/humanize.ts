/**
 * Customer-readable labels for automation primitives.
 *
 * Each helper takes a backend value (enum string, cron expression, etc.) and
 * returns a friendlier string. Raw values flow through as fallback so the UI
 * never crashes on unknown inputs from a newer backend.
 */

import type {
  AutomationActionType,
  AutomationRunStatus,
  AutomationTriggerKind,
  AutomationWorkspaceScope,
  CommunicationDestinationKind,
} from '../../../types/automations';

const WEEKDAY_NAMES = [
  'Sunday',
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
];

const MONTH_NAMES = [
  '',
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

function fmtTimeOfDay(hourField: string, minuteField: string): string | null {
  const h = parseInt(hourField, 10);
  const m = parseInt(minuteField, 10);
  if (!Number.isFinite(h) || !Number.isFinite(m)) return null;
  if (h < 0 || h > 23 || m < 0 || m > 59) return null;
  const period = h < 12 ? 'AM' : 'PM';
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return `${hour12}:${m.toString().padStart(2, '0')} ${period}`;
}

function describeWeekday(field: string): string | null {
  if (field === '*') return null;
  if (field === '1-5') return 'every weekday';
  if (field === '0,6' || field === '6,0') return 'every weekend day';
  if (/^\d$/.test(field)) {
    const idx = parseInt(field, 10);
    // cron supports 0 OR 7 as Sunday
    const norm = idx === 7 ? 0 : idx;
    if (norm >= 0 && norm <= 6) return `every ${WEEKDAY_NAMES[norm]}`;
  }
  return null;
}

function describeDayOfMonth(field: string): string | null {
  if (field === '*') return null;
  if (/^\d{1,2}$/.test(field)) {
    const day = parseInt(field, 10);
    if (day >= 1 && day <= 31) {
      const suffix =
        day % 10 === 1 && day !== 11
          ? 'st'
          : day % 10 === 2 && day !== 12
            ? 'nd'
            : day % 10 === 3 && day !== 13
              ? 'rd'
              : 'th';
      return `on the ${day}${suffix}`;
    }
  }
  return null;
}

function describeMonth(field: string): string | null {
  if (field === '*') return null;
  if (/^\d{1,2}$/.test(field)) {
    const m = parseInt(field, 10);
    if (m >= 1 && m <= 12) return `in ${MONTH_NAMES[m]}`;
  }
  return null;
}

/**
 * Best-effort humanizer for 5-field cron expressions. Falls back to the
 * raw expression for anything we don't explicitly handle (ranges, lists
 * across multiple fields, complex step values, etc.).
 *
 * Examples handled: "0 9 * * 1-5" -> "Every weekday at 9:00 AM"
 *                   "30 14 * * *" -> "Every day at 2:30 PM"
 *                   "0 * * * *"   -> "Every hour"
 *                   "[STAR]/15 * * * *" -> "Every 15 minutes" (literal "*" + "/15")
 */
export function humanizeCron(
  expression: string | undefined | null,
  timezone?: string | null
): string {
  const raw = (expression ?? '').trim();
  if (!raw) return '—';
  const parts = raw.split(/\s+/);
  if (parts.length < 5 || parts.length > 6) return raw;
  const [minute, hour, dayOfMonth, month, weekday] = parts;
  const tzSuffix = timezone && timezone !== 'UTC' ? ` (${timezone})` : '';

  // Every minute
  if (minute === '*' && hour === '*' && dayOfMonth === '*' && month === '*' && weekday === '*') {
    return `Every minute${tzSuffix}`;
  }

  // Every N minutes
  const stepMatch = /^\*\/(\d{1,2})$/.exec(minute);
  if (stepMatch && hour === '*' && dayOfMonth === '*' && month === '*' && weekday === '*') {
    return `Every ${stepMatch[1]} minutes${tzSuffix}`;
  }

  // Every hour at minute M
  if (
    /^\d{1,2}$/.test(minute) &&
    hour === '*' &&
    dayOfMonth === '*' &&
    month === '*' &&
    weekday === '*'
  ) {
    const m = parseInt(minute, 10);
    if (m === 0) return `Every hour${tzSuffix}`;
    return `Every hour at :${m.toString().padStart(2, '0')}${tzSuffix}`;
  }

  // Daily / weekly at a specific time
  if (/^\d{1,2}$/.test(minute) && /^\d{1,2}$/.test(hour)) {
    const time = fmtTimeOfDay(hour, minute);
    if (time) {
      const wd = describeWeekday(weekday);
      const dom = describeDayOfMonth(dayOfMonth);
      const mo = describeMonth(month);
      if (wd && dayOfMonth === '*' && month === '*') {
        const cap = wd.charAt(0).toUpperCase() + wd.slice(1);
        return `${cap} at ${time}${tzSuffix}`;
      }
      if (!wd && !dom && !mo) {
        return `Every day at ${time}${tzSuffix}`;
      }
      if (dom && month === '*' && weekday === '*') {
        return `${dom.charAt(0).toUpperCase() + dom.slice(1)} of every month at ${time}${tzSuffix}`;
      }
      if (dom && mo && weekday === '*') {
        return `Every year ${mo} ${dom} at ${time}${tzSuffix}`;
      }
    }
  }

  // Fall through to raw expression so we never lie about the schedule.
  return tzSuffix ? `${raw}${tzSuffix}` : raw;
}

const TRIGGER_KIND_LABELS: Record<AutomationTriggerKind, string> = {
  cron: 'On a schedule',
  webhook: 'When a URL receives data',
  manual: 'Only when I run it',
  app_invocation: 'When an app calls it',
};

export function humanizeTriggerKind(kind: AutomationTriggerKind | string): string {
  return TRIGGER_KIND_LABELS[kind as AutomationTriggerKind] ?? String(kind);
}

const ACTION_TYPE_LABELS: Record<AutomationActionType, string> = {
  'agent.run': 'Run an AI agent',
  'app.invoke': 'Use one of my apps',
  'gateway.send': 'Send a message',
};

export function humanizeActionType(type: AutomationActionType | string): string {
  return ACTION_TYPE_LABELS[type as AutomationActionType] ?? String(type);
}

const WORKSPACE_SCOPE_LABELS: Record<AutomationWorkspaceScope, string> = {
  none: 'No files needed',
  user_automation_workspace: 'In my personal automation folder',
  team_automation_workspace: "In our team's automation folder",
  target_project: 'Inside one of my projects',
};

export function humanizeWorkspaceScope(scope: AutomationWorkspaceScope | string): string {
  return WORKSPACE_SCOPE_LABELS[scope as AutomationWorkspaceScope] ?? String(scope);
}

const RUN_STATUS_LABELS: Record<AutomationRunStatus, string> = {
  queued: 'Waiting to start',
  running: 'Running',
  awaiting_approval: 'Needs your OK',
  paused: 'Paused',
  succeeded: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
  expired: 'Timed out',
};

export function humanizeRunStatus(status: AutomationRunStatus | string): string {
  return RUN_STATUS_LABELS[status as AutomationRunStatus] ?? String(status || 'Unknown');
}

const DESTINATION_KIND_LABELS: Record<CommunicationDestinationKind, string> = {
  slack_channel: 'Slack channel',
  slack_dm: 'Slack DM',
  slack_thread: 'Slack thread',
  telegram_chat: 'Telegram chat',
  telegram_topic: 'Telegram topic',
  discord_channel: 'Discord channel',
  discord_dm: 'Discord DM',
  email: 'Email',
  webhook: 'Webhook',
  web_inbox: 'Web inbox',
};

export function humanizeDestinationKind(kind: CommunicationDestinationKind | string): string {
  return DESTINATION_KIND_LABELS[kind as CommunicationDestinationKind] ?? String(kind);
}
