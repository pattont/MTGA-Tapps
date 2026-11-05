import { useRef } from 'react';
import { X } from 'lucide-react';
import { addTags } from '../tagList';

export interface TagInputProps {
  tags: string[];
  /** Text typed but not yet turned into a tag; saving includes it. */
  draft: string;
  onChange: (tags: string[], draft: string) => void;
  disabled?: boolean;
}

/** Tags as removable chips with a text box after them: Enter or a comma adds one. */
export function TagInput({ tags, draft, onChange, disabled }: TagInputProps) {
  const input = useRef<HTMLInputElement>(null);
  return (
    // Clicking the empty part of the box focuses the text field, like a normal input.
    <div className="tag-input" onClick={(event) => { if (event.target === event.currentTarget) input.current?.focus(); }}>
      {tags.map((tag) => (
        <span key={tag} className="tag-input-chip">
          {tag}
          <button type="button" disabled={disabled} aria-label={`Remove tag ${tag}`} onClick={() => onChange(tags.filter((t) => t !== tag), draft)}>
            <X size={12} aria-hidden="true" />
          </button>
        </span>
      ))}
      <input
        ref={input}
        aria-label="Tags"
        value={draft}
        disabled={disabled}
        placeholder={tags.length ? 'Add a tag' : 'Add tags, like aggro or best-of-three'}
        onChange={(event) => {
          // Typing or pasting a comma finishes every tag before it.
          const parts = event.target.value.split(',');
          const rest = parts.pop() ?? '';
          onChange(parts.length ? addTags(tags, parts) : tags, parts.length ? rest.trimStart() : rest);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            if (draft.trim()) onChange(addTags(tags, [draft]), '');
          } else if (event.key === 'Backspace' && !draft && tags.length) {
            onChange(tags.slice(0, -1), '');
          }
        }}
      />
    </div>
  );
}
