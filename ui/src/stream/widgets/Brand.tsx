import { PRODUCT_NAME } from '../../branding';

/** The small credit under each widget (`brand=0` hides it). */
export function Brand({ show }: { show: boolean }) {
  if (!show) return null;
  return <div className="sk-brand">{PRODUCT_NAME}</div>;
}
