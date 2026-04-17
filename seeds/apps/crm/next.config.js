/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Standalone output skips static-export prerendering, which crashes on
  // Node 22-alpine (devserver base) with a useContext null error in
  // Next 16's _global-error page. Standalone produces a self-contained
  // server bundle that works everywhere.
  output: 'standalone',
  typescript: { ignoreBuildErrors: true },
  experimental: {
    serverActions: {},
  },
  async headers() {
    // Permit framing from any origin so the Tesslate shell can embed this app
    // in an iframe. The shell enforces postMessage origin pairing separately.
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Frame-Options', value: 'ALLOWALL' },
          {
            key: 'Content-Security-Policy',
            value: "frame-ancestors *;",
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
