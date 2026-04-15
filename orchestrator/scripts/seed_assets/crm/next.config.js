/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
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
