/** On/off switch beside a feature card's title; it saves as soon as it flips. */
export function FeatureSwitch({
  label,
  checked,
  busy,
  onChange,
}: {
  label: string;
  checked: boolean;
  busy: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <button
      aria-checked={checked}
      aria-label={label}
      className="settings-switch"
      disabled={busy}
      role="switch"
      type="button"
      onClick={() => onChange(!checked)}
    >
      <span aria-hidden="true" className="settings-switch-track">
        <span className="settings-switch-thumb" />
      </span>
      {checked ? 'On' : 'Off'}
    </button>
  );
}
