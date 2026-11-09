# syntax=docker/dockerfile:1
# Review viewer image: build the static site with Node, serve it with unprivileged nginx.
# Educational use only. Build from frontend/:  docker build --build-arg VITE_API_BASE_URL=... .

# ---- build: Node 22.23.4 (Debian slim), pinned by digest ----
FROM node@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS build
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .

# Vite builds this into the page, so it must be the API address as seen from the browser
# (on the host), not a compose service name. Never put a secret in a VITE_ variable.
ARG VITE_API_BASE_URL=http://127.0.0.1:8000
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

# vite build only: `npm run build` also runs tsc -b over the tests, and types.test.ts reads
# docs/openapi.json from outside this build context. The type check runs in CI and before
# every commit instead.
RUN npx vite build

# ---- serve: nginx 1.30.6 unprivileged (runs as a non-root user on port 8080) ----
FROM nginxinc/nginx-unprivileged@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
