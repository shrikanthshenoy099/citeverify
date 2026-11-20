/** @type {import('next').NextConfig} */
const rawApiUrl =
  process.env.NEXT_PUBLIC_API_URL || "https://citeverify-e8s0.onrender.com";
const apiUrl = rawApiUrl.replace(/\/+$/, "");

const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;