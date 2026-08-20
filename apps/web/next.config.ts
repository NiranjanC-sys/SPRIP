import type { NextConfig } from 'next';

/**
 * The portal is served from the same origin as the API in every deployment we
 * support (a reverse proxy fronts both), so `/api/v1/*` is rewritten rather than
 * called cross-origin. That keeps the session cookie `SameSite=Lax` — a
 * cross-origin API would force `SameSite=None`, which we are not willing to ship
 * for a compliance product.
 */
const API_ORIGIN = process.env.API_ORIGIN ?? 'http://localhost:8000';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,

  // Fail the build on a type error or lint error. A green `next build` is the
  // gate this project uses, so silencing either would make the gate meaningless.
  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: false },

  experimental: {
    // echarts ships a very large barrel; per-module resolution keeps the
    // client bundle to the chart types actually imported.
    optimizePackageImports: ['echarts', 'lucide-react'],
  },

  async rewrites() {
    return [{ source: '/api/v1/:path*', destination: `${API_ORIGIN}/api/v1/:path*` }];
  },

  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          // The portal never needs these; denying them shrinks the attack
          // surface a hostile upload preview could reach for.
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=(), payment=()' },
        ],
      },
      {
        // Self-hosted fonts are content-addressed by next/font, so they are
        // safe to cache immutably. This is what makes the offline demo instant.
        source: '/fonts/:path*',
        headers: [{ key: 'Cache-Control', value: 'public, max-age=31536000, immutable' }],
      },
    ];
  },
};

export default nextConfig;
