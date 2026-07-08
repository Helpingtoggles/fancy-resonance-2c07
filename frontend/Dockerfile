FROM node:20-alpine AS deps
WORKDIR /srv
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

FROM node:20-alpine AS build
WORKDIR /srv
COPY --from=deps /srv/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS run
WORKDIR /srv
ENV NODE_ENV=production
RUN addgroup -S app && adduser -S app -G app
COPY --from=build --chown=app:app /srv/.next/standalone ./
COPY --from=build --chown=app:app /srv/.next/static ./.next/static
USER app
EXPOSE 3000
CMD ["node", "server.js"]
