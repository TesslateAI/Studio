# ── Build stage ─────────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

# Install all deps (incl. TypeScript) for the build.
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY tsconfig.json ./
COPY src ./src

RUN npm run build

# Prune dev deps so we can copy a lean node_modules into the runtime stage.
RUN npm prune --omit=dev


# ── Runtime stage ───────────────────────────────────────────────────
FROM node:20-alpine

WORKDIR /app

COPY --from=build /app/package.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist

# Non-root user (the `node` user ships with the node:alpine image).
USER node

ENV NODE_ENV=production
ENV AST_BIND_HOST=0.0.0.0
ENV AST_BIND_PORT=9000

EXPOSE 9000

CMD ["node", "dist/src/server.js"]
