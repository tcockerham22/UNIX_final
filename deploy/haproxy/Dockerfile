FROM haproxy:3.2.3-alpine3.22

USER root
RUN apk add --no-cache gettext
COPY haproxy.cfg.template /usr/local/etc/haproxy/haproxy.cfg.template
COPY render-and-start.sh /usr/local/bin/render-and-start
RUN chmod 0555 /usr/local/bin/render-and-start
USER haproxy
ENTRYPOINT ["/usr/local/bin/render-and-start"]
