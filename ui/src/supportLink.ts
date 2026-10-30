// Buy Me a Coffee page for the sidebar's support button. Put your username here:
// the part after buymeacoffee.com/ (for https://buymeacoffee.com/tapps, use 'tapps').
// While it is empty the button stays hidden.
export const BUY_ME_A_COFFEE_USERNAME = 'tappsters';

const USERNAME_PATTERN = /^[A-Za-z0-9_-]+$/;

export function buyMeACoffeeUrl(username: string = BUY_ME_A_COFFEE_USERNAME): string | null {
  const name = username.trim().replace(/^@/, '');
  if (!USERNAME_PATTERN.test(name)) return null;
  return `https://buymeacoffee.com/${name}`;
}
