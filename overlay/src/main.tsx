import { render } from 'preact';
import { App } from './App';
import { log } from './tauri';
import './styles.css';

window.addEventListener('error', (event) => log(`error: ${event.message} (${event.filename}:${event.lineno})`));
window.addEventListener('unhandledrejection', (event) => log(`unhandled rejection: ${String(event.reason)}`));
log('page loaded');

// The overlay is a game HUD: no context menu, no text selection, no zoom.
document.addEventListener('contextmenu', (event) => event.preventDefault());
document.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && ['+', '-', '=', '0'].includes(event.key)) event.preventDefault();
});

render(<App />, document.getElementById('root')!);
