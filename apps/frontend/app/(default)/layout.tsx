import { ResumePreviewProvider } from '@/components/common/resume_previewer_context';
import { StatusCacheProvider } from '@/lib/context/status-cache';
import { LanguageProvider } from '@/lib/context/language-context';
import { LocalizedErrorBoundary } from '@/components/common/error-boundary';
import { ToastProvider } from '@/components/ui/toast';

export default function DefaultLayout({ children }: { children: React.ReactNode }) {
  return (
    <StatusCacheProvider>
      <LanguageProvider>
        <ResumePreviewProvider>
          <LocalizedErrorBoundary>
            <ToastProvider>
              <main className="min-h-screen flex flex-col">{children}</main>
            </ToastProvider>
          </LocalizedErrorBoundary>
        </ResumePreviewProvider>
      </LanguageProvider>
    </StatusCacheProvider>
  );
}
