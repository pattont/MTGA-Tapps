import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { StreamRoot } from './StreamApp';
import './stream.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <StreamRoot />
  </StrictMode>,
);
