/** @type {import('next').NextConfig} */
const apiUrl = process.env.API_URL || "http://localhost:3001";

module.exports = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/:path*`,
      },
    ];
  },
};
