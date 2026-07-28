import type { Metadata } from 'next';
import './globals.css';
import NavBar from './NavBar';
import { PersonaProvider } from './PersonaContext';
import { AuthProvider } from './AuthContext';
import { ThemeProvider } from './ThemeContext';
import { ScenarioProvider } from './ScenarioContext';
import { ActiveAnalysisProvider } from './ActiveAnalysisContext';
import AuthGuard from './AuthGuard';

export const metadata: Metadata = {
  title: 'InvestIQ — Capital Decision Intelligence',
  description: 'Investment Capital Decision Intelligence platform with auditable outputs',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="overflow-x-hidden" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: `try{if(localStorage.getItem('investiq_theme')==='light')document.documentElement.setAttribute('data-theme','light')}catch(e){}` }} />
      </head>
      <body>
        <AuthProvider>
          <PersonaProvider>
            <ScenarioProvider>
              <ThemeProvider>
                <ActiveAnalysisProvider>
                  <AuthGuard>
                    <div className="min-h-screen overflow-x-hidden bg-d-bg">
                      <NavBar />
                      <main className="max-w-[1600px] mx-auto px-4 py-6">{children}</main>
                    </div>
                  </AuthGuard>
                </ActiveAnalysisProvider>
              </ThemeProvider>
            </ScenarioProvider>
          </PersonaProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
