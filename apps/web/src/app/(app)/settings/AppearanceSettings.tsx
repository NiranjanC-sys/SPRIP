'use client';

import * as React from 'react';
import { useTheme } from 'next-themes';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { RadioGroup, RadioOption } from '@/components/ui/radio-group';
import { Skeleton } from '@/components/ui/skeleton';

/**
 * Theme preference.
 *
 * Three options, not two. "System" is the default and has to stay reachable: a
 * user who tries dark mode, dislikes it, and cannot get back to "follow my OS"
 * has been given a worse setting than they started with.
 *
 * The choice is stored per browser (`localStorage`, key `sr.theme`) rather than
 * on the account, deliberately. The same analyst uses a bright meeting-room
 * display and a dim home office; syncing a theme across those is a misfeature.
 */
export function AppearanceSettings() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  // `theme` is undefined until next-themes has read localStorage on the client.
  // Rendering the radio list before then would paint the wrong option selected
  // for one frame and, worse, produce a hydration mismatch.
  React.useEffect(() => setMounted(true), []);

  return (
    <Card>
      <CardHeader bordered>
        <CardTitle>Appearance</CardTitle>
        <CardDescription>
          Applies to this browser only. Both themes are held to the same contrast standard, so
          neither is a degraded mode.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {mounted ? (
          <RadioGroup value={theme ?? 'system'} onValueChange={setTheme} aria-label="Theme">
            <RadioOption
              value="system"
              label="Match my system"
              description="Follows your operating system's light or dark setting, and changes with it."
            />
            <RadioOption
              value="light"
              label="Light"
              description="Best on bright displays and for anything you intend to project or print."
            />
            <RadioOption
              value="dark"
              label="Dark"
              description="Lower emitted light for long analysis sessions. Chart palettes are re-tuned, not merely inverted."
            />
          </RadioGroup>
        ) : (
          <div className="flex flex-col gap-3">
            {Array.from({ length: 3 }, (_, i) => (
              <Skeleton key={i} className="h-9 w-full" label={i === 0 ? 'Loading appearance settings' : undefined} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
