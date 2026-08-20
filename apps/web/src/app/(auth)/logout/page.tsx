import type { Metadata } from 'next';

import { LogoutRunner } from './LogoutRunner';

export const metadata: Metadata = { title: 'Signing out' };

export default function LogoutPage() {
  return <LogoutRunner />;
}
