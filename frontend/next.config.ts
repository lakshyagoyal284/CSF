import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the workspace root: without this, Turbopack walks up to a lockfile in a
  // parent directory and warns about including the whole home directory.
  turbopack: {
    root: path.resolve(__dirname),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  cacheComponents: true,
  partialPrefetching: true,
};

export default nextConfig;
