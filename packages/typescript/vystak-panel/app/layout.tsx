import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Vystak Panel',
  description: 'Control panel for deployed Vystak agents',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
