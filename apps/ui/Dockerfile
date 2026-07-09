FROM node:20-alpine AS base

FROM base AS deps
WORKDIR /app
COPY apps/ui/package.json apps/ui/package-lock.json* ./
RUN npm ci || npm install

FROM base AS builder
WORKDIR /app
ENV API_PROXY_TARGET=http://api:8000
COPY --from=deps /app/node_modules ./node_modules
COPY apps/ui/ .
RUN chmod -R +x node_modules/.bin && npm run build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV API_PROXY_TARGET=http://api:8000

CMD ["node", "server.js"]
