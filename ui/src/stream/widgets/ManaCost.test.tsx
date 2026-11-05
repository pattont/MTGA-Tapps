import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ManaCost } from './ManaCost';

describe('stream ManaCost', () => {
  it('draws costs like the in-game overlay: color vectors and grey badges', () => {
    const { container } = render(<ManaCost cost="{5}{R}{W/U}{X}" />);
    const mana = container.querySelector('.mana') as HTMLElement;
    expect(mana).toHaveAttribute('aria-label', '{5}{R}{W/U}{X}');
    expect(Array.from(mana.querySelectorAll('img'), (img) => img.getAttribute('src'))).toEqual(['/icons/R.svg']);
    const badges = Array.from(mana.querySelectorAll('i.gen'), (badge) => [badge.textContent, badge.className]);
    expect(badges).toEqual([
      ['5', 'gen'],
      ['W/U', 'gen hybrid'],
      ['X', 'gen'],
    ]);
    // The dashboard's mana-font glyphs stay out of the stream.
    expect(container.querySelector('.ms')).toBeNull();
  });

  it('leaves an empty slot for lands and unknown costs', () => {
    const { container } = render(<ManaCost cost={null} />);
    expect(container.querySelector('.mana')).toBeEmptyDOMElement();
  });
});
