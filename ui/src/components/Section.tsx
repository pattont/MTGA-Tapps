import type { ReactNode } from 'react';
import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

/**
 * Shared page section. Collapsible everywhere so long pages can be tidied;
 * previously four near-identical copies existed (only the game page could
 * collapse).
 */
export function Section({
  id,
  title,
  description,
  children,
  collapsible = true,
}: {
  id: string;
  /** Omit when the page heading already names this content (e.g. All Games). */
  title?: string;
  description?: string;
  children: ReactNode;
  collapsible?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const contentId = `${id}-content`;

  if (!collapsible) {
    return (
      <section className="dashboard-section" id={id}>
        <div className="section-heading">
          <div>
            {title ? <h3>{title}</h3> : null}
            {description ? <p className="section-description">{description}</p> : null}
          </div>
        </div>
        {children}
      </section>
    );
  }

  return (
    <section
      className={collapsed ? 'dashboard-section dashboard-section-collapsed' : 'dashboard-section'}
      id={id}
    >
      <div className="section-heading">
        {title ? <h3>{title}</h3> : <span aria-hidden="true" />}
        <button
          type="button"
          className="section-collapse-button"
          aria-controls={contentId}
          aria-expanded={!collapsed}
          aria-label={`${collapsed ? 'Expand' : 'Collapse'} ${title ?? 'section'}`}
          title={`${collapsed ? 'Expand' : 'Collapse'} ${title ?? 'section'}`}
          onClick={() => setCollapsed((current) => !current)}
        >
          {collapsed ? <ChevronDown aria-hidden="true" /> : <ChevronUp aria-hidden="true" />}
        </button>
      </div>
      <div className="section-content" id={contentId} hidden={collapsed}>
        {description ? <p className="section-description">{description}</p> : null}
        {children}
      </div>
    </section>
  );
}
