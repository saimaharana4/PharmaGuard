FROM nginxinc/nginx-unprivileged:stable-alpine
USER root
COPY infra/edge/default.conf.template /etc/nginx/templates/default.conf.template
RUN rm -f /etc/nginx/conf.d/default.conf
USER 101
ENV PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/api/health || exit 1
