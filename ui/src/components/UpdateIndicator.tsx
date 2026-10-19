import { useState, type ReactNode } from 'react';
import { ArrowUpCircle, Download, RefreshCw, X } from 'lucide-react';
import { displayVersion, updatePillModel, type UpdatePillModel } from '../updateStatus';
import type { UpdateController } from './useUpdateStatus';

const RING_RADIUS = 14;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

function CollapsedIcon({ model, installing }: { model: UpdatePillModel; installing: boolean }) {
  if (installing) {
    return <RefreshCw aria-hidden="true" className="sidebar-update-spin" />;
  }
  if (model.kind === 'retry') {
    return <RefreshCw aria-hidden="true" />;
  }
  if (model.kind === 'download' || model.kind === 'progress') {
    return <Download aria-hidden="true" />;
  }
  return <ArrowUpCircle aria-hidden="true" />;
}

/**
 * The sidebar's update affordance. Expanded: a pill above the launchers.
 * Collapsed: a 32 px icon button with a progress ring while downloading.
 */
export function UpdateIndicator({
  controller,
  collapsed = false,
}: {
  controller: UpdateController;
  collapsed?: boolean;
}) {
  const { status, busy, notice } = controller;
  const model = updatePillModel(status);
  if (!model.visible || (collapsed && !model.showCollapsed)) {
    return null;
  }
  const version = displayVersion(status?.latest_version);

  async function activate() {
    if (model.kind === 'download') {
      await controller.download();
    } else if (model.kind === 'retry') {
      await controller.check();
    } else if (model.kind === 'install') {
      const refusal = await controller.install();
      // The collapsed rail has no room for the inline choice: ask instead.
      if (collapsed && refusal?.kind === 'game' && window.confirm(`${refusal.text}. Install after this game instead?`)) {
        await controller.installAfterGame();
      }
    }
  }

  if (collapsed) {
    const ariaLabel =
      model.kind === 'install' ? `Restart to update${version ? ` to ${version}` : ''}` : model.label;
    const title = notice ? `${notice.text} — ${model.title}` : model.title;
    const className = `sidebar-update-mini sidebar-update-mini-${model.kind}`;
    const ring =
      model.kind === 'progress' ? (
        <svg aria-hidden="true" className="sidebar-update-ring" viewBox="0 0 32 32">
          <circle className="sidebar-update-ring-track" cx="16" cy="16" r={RING_RADIUS} />
          <circle
            className="sidebar-update-ring-fill"
            cx="16"
            cy="16"
            r={RING_RADIUS}
            strokeDasharray={RING_CIRCUMFERENCE}
            strokeDashoffset={RING_CIRCUMFERENCE * (1 - (model.percent ?? 0) / 100)}
          />
        </svg>
      ) : null;
    const icon = <CollapsedIcon installing={status?.state === 'installing'} model={model} />;
    if (model.kind === 'link') {
      return (
        <a aria-label={ariaLabel} className={className} href={model.href} rel="noreferrer" target="_blank" title={title}>
          {icon}
        </a>
      );
    }
    if (model.kind === 'progress' || model.kind === 'none') {
      return (
        <span aria-label={ariaLabel} className={className} role="status" title={title}>
          {ring}
          {icon}
        </span>
      );
    }
    return (
      <button aria-label={ariaLabel} className={className} disabled={busy} title={title} type="button" onClick={() => void activate()}>
        {icon}
      </button>
    );
  }

  let pill: ReactNode;
  if (model.kind === 'link') {
    pill = (
      <a className="sidebar-update" href={model.href} rel="noreferrer" target="_blank" title={model.title}>
        {model.label}
      </a>
    );
  } else if (model.kind === 'progress') {
    pill = (
      <div className="sidebar-update sidebar-update-progress" role="status" title={model.title}>
        <span>{model.label}</span>
        {model.percent === undefined ? (
          <progress aria-label="Update download progress" className="sidebar-update-bar" />
        ) : (
          <progress
            aria-label="Update download progress"
            aria-valuemax={100}
            aria-valuemin={0}
            aria-valuenow={model.percent}
            className="sidebar-update-bar"
            max={100}
            value={model.percent}
          />
        )}
      </div>
    );
  } else if (model.kind === 'none') {
    pill = (
      <span className="sidebar-update sidebar-update-installing" role="status" title={model.title}>
        <RefreshCw aria-hidden="true" className="sidebar-update-spin" />
        {model.label}
      </span>
    );
  } else {
    pill = (
      <button
        className={`sidebar-update sidebar-update-${model.kind}`}
        disabled={busy}
        title={model.title}
        type="button"
        onClick={() => void activate()}
      >
        {model.label}
      </button>
    );
  }

  return (
    <div className="sidebar-update-slot">
      {pill}
      {status?.pending_install ? (
        <p className="sidebar-update-note" role="status">
          Will install after this game
        </p>
      ) : notice?.kind === 'game' ? (
        <>
          <p className="sidebar-update-note" role="status">
            {notice.text}
          </p>
          <button
            className="sidebar-update-secondary"
            disabled={busy}
            type="button"
            onClick={() => void controller.installAfterGame()}
          >
            Install after this game
          </button>
        </>
      ) : notice ? (
        <p className="sidebar-update-note sidebar-update-note-warn" role="alert">
          {notice.text}
        </p>
      ) : null}
    </div>
  );
}

/** "Updated to vX · What's new" (once per install) and the newer-database warning. */
export function UpdateNotices({ controller }: { controller: UpdateController }) {
  const [dismissed, setDismissed] = useState<string | null>(null);
  const status = controller.status;
  const justUpdated = status?.just_updated ?? null;
  const showJustUpdated = justUpdated !== null && dismissed !== justUpdated.to;
  if (!showJustUpdated && !status?.db_newer_than_app) {
    return null;
  }
  return (
    <>
      {showJustUpdated && justUpdated ? (
        <p className={`sidebar-just-updated${justUpdated.ok ? '' : ' sidebar-just-updated-failed'}`} role="status">
          <span>
            {justUpdated.ok
              ? `Updated to ${displayVersion(justUpdated.to)}`
              : `Update to ${displayVersion(justUpdated.to)} did not finish`}
            {justUpdated.notes_url ? (
              <>
                {' · '}
                <a href={justUpdated.notes_url} rel="noreferrer" target="_blank">
                  {justUpdated.ok ? "What's new" : 'Details'}
                </a>
              </>
            ) : null}
          </span>
          <button
            aria-label="Dismiss update notice"
            className="sidebar-just-updated-dismiss"
            title="Dismiss"
            type="button"
            onClick={() => {
              setDismissed(justUpdated.to);
              void controller.acknowledge();
            }}
          >
            <X aria-hidden="true" />
          </button>
        </p>
      ) : null}
      {status?.db_newer_than_app ? (
        <p className="sidebar-update-warning" role="alert" title="This database was written by a newer Tapps Tracker; update to the latest version.">
          Database is newer than this version
        </p>
      ) : null}
    </>
  );
}
