import { describe, expect, it } from 'vitest';
import { buyMeACoffeeUrl } from './supportLink';

describe('buyMeACoffeeUrl', () => {
  it('hides the button until a username is set', () => {
    expect(buyMeACoffeeUrl('')).toBeNull();
    expect(buyMeACoffeeUrl('   ')).toBeNull();
  });

  it('builds the page link from the username', () => {
    expect(buyMeACoffeeUrl('tapps')).toBe('https://buymeacoffee.com/tapps');
    expect(buyMeACoffeeUrl(' @tapps_tracker ')).toBe('https://buymeacoffee.com/tapps_tracker');
  });

  it('rejects anything that is not a plain username', () => {
    expect(buyMeACoffeeUrl('https://buymeacoffee.com/tapps')).toBeNull();
    expect(buyMeACoffeeUrl('tapps/../x')).toBeNull();
  });
});
