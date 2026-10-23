FROM node:24-trixie-slim@sha256:7f486cabe892bff8fef04c0f7da8dba84a560be3e4e2740b7a86afc57ebec315 AS build
WORKDIR /app
RUN npm install --global pnpm@12.14.0
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/web ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build
RUN mkdir -p /runtime-cache && chown 65532:65532 /runtime-cache

FROM gcr.io/distroless/nodejs24-debian13:nonroot@sha256:78f07ef1b5ea71ad7c055df15d0dd8997f2d288f9158623c4d4ae3d765b7d50d AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=8080
WORKDIR /app
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
COPY --from=build --chown=65532:65532 /runtime-cache ./.next/cache
USER 65532:65532
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD ["/nodejs/bin/node", "-e", "const r=require('http').get('http://127.0.0.1:8080/api/health',s=>{s.resume();process.exit(s.statusCode===200?0:1)});r.setTimeout(3000,()=>{r.destroy();process.exit(1)});r.on('error',()=>process.exit(1))"]
ENTRYPOINT []
CMD ["/nodejs/bin/node", "server.js"]
