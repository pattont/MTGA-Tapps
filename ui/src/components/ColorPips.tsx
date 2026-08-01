const WUBRG = 'WUBRG';

/** Small mana-color pips for a WUBRG letter string (e.g. "UR"). */
export function ColorPips({ colors }: { colors: string | null | undefined }) {
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
          height={15}
          src={`/icons/${letter}.svg`}
          width={15}
        />
      ))}
    </span>
  );
}
