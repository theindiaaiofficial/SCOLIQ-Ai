import { StrictMode } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import App from './App';
import { BrandProvider } from './features/branding/BrandProvider';
import './styles/tokens.css';
import './styles/global.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 20_000, retry: (failureCount, error) => failureCount < 1 && (!(error instanceof Error) || !('status' in error) || (error as { status: number }).status >= 500) },
    mutations: { retry: false },
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <BrandProvider>
          <App />
          <Toaster position="top-right" richColors closeButton />
        </BrandProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
