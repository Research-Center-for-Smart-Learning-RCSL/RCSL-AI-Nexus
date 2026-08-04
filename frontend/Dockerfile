# Built on the Mac Studio (arm64). One image serves both admin entrances;
# they differ only in the ADMIN_API_URL the rewrite targets, supplied at run
# time by docker-compose.yml.
FROM node:22-alpine AS deps
WORKDIR /app
RUN corepack enable
# `pnpm-workspace.yaml` is not optional and was missing here until 2026-08-04.
# It is where pnpm 10 reads settings the `pnpm` field in package.json no longer
# carries: the `overrides` that pin postcss and sharp onto their patched lines,
# and the build-script allowlist. Without it in this stage `--frozen-lockfile`
# refuses outright once the lockfile records an override, and before that it
# built quietly with the allowlist simply absent — the intent stated in the repo
# and enforced nowhere in the image.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:22-alpine AS builder
WORKDIR /app
RUN corepack enable
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Enables `output: 'standalone'`; see the comment in next.config.js for why
# this is opt-in rather than always on.
ENV NEXT_OUTPUT=standalone
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup -g 10001 -S nodejs && adduser -u 10001 -S nextjs -G nodejs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

CMD ["node", "server.js"]
