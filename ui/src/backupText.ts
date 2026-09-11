import type { BackupPreview } from './api';

export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

/** What a restore would do here, in one sentence, and whether it needs the word. */
export function describePreview(preview: BackupPreview): { text: string; blocked: boolean } {
  const m = preview.manifest;
  const games = plural(m.games, 'game');
  switch (preview.verdict) {
    case 'newer-schema':
      return {
        text: `This backup was made by a newer tracker (database schema ${m.schema_version}; this build knows ${preview.supported_schema_version}). Update the tracker first.`,
        blocked: true,
      };
    case 'fresh':
      return { text: `This computer has no games yet. The backup's ${games} come in.`, blocked: false };
    case 'same':
      return { text: `Same ${games} as here. Restoring only brings over the backup's settings.`, blocked: false };
    case 'newer':
      return {
        text: `Adds ${plural(preview.adds, 'game')} this computer does not have. Nothing recorded here is lost.`,
        blocked: false,
      };
    case 'older':
      return {
        text: `Older than what is here: restoring would drop ${plural(preview.drops, 'game')} recorded on this computer that the backup does not have.`,
        blocked: false,
      };
    case 'diverged':
    default:
      return {
        text: `Adds ${plural(preview.adds, 'game')} from the backup and drops ${plural(preview.drops, 'game')} recorded here that it does not have.`,
        blocked: false,
      };
  }
}
