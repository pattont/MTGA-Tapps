import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { parseStreamOptions } from './options';
import { StreamApp } from './StreamApp';
import './stream.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <StreamApp options={parseStreamOptions(window.location.search)} />
  </StrictMode>,
);
