import { createContext } from 'react';
import type { SnapshotFilters } from './api';

export const RouteFiltersContext = createContext<SnapshotFilters>({});
