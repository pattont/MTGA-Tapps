const WUBRG = 'WUBRG';

/** Small mana-color pips for a WUBRG letter string (e.g. "UR"). */
export function ColorPips({
  colors,
  size = 15,
}: {
  colors: string | null | undefined;
  size?: number;
}) {
  const letters = Array.from(String(colors ?? '')).filter((letter) => WUBRG.includes(letter));
  if (letters.length === 0) {
    return null;
  }
  return (
    <span className="color-pips" role="img" aria-label={`Colors: ${letters.join(', ')}`}>
      {letters.map((letter) => (
        <img
          key={letter}
          alt={letter}
          className="color-pip"
          height={size}
          src={`/icons/${letter}.svg`}
          width={size}
        />
      ))}
    </span>
  );
}
