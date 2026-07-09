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

  // Show introduction / welcome page on first visit
  if (showIntro && pathname !== '/login') {
    return (
      <IntroductionPage
        onSkip={() => setShowIntro(false)}
      />
    );
  }

  // Show app
  return <>{children}</>;
}
