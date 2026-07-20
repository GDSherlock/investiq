'use client';

import { useState } from 'react';
import { useAuth } from './AuthContext';
import { usePathname } from 'next/navigation';
import IntroductionPage from './IntroductionPage';

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isLoading } = useAuth();
  const pathname = usePathname();
  const [showIntro, setShowIntro] = useState(true);

  // Show loading while initialising
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-d-bg">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gold-500 mx-auto"></div>
          <p className="mt-4 text-d-muted">Loading...</p>
        </div>
      </div>
    );
  }

  // Keep the application mounted behind the introduction so hydration and
  // persisted calculation restore are not deferred until Skip.
  return (
    <>
      {children}
      {showIntro && pathname !== '/login' ? (
        <IntroductionPage onSkip={() => setShowIntro(false)} />
      ) : null}
    </>
  );
}
