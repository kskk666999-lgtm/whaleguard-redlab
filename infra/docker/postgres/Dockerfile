# Keep the upstream release and base filesystem immutable. Alpine security
# packages are refreshed below and the resulting image is scanned before use.
FROM postgres:16.15-alpine3.23@sha256:421b84e07a72bb8f3715f20501a1fdbe1219aad1fa4af7786a49d9a3f2480296

LABEL org.opencontainers.image.title="WhaleGuard PostgreSQL"
LABEL org.opencontainers.image.description="Security-refreshed PostgreSQL for WhaleGuard AI RedLab"
LABEL org.opencontainers.image.base.name="docker.io/library/postgres:16.15-alpine3.23"

RUN apk upgrade --no-cache libcrypto3 libssl3 \
    && apk add --no-cache su-exec

# The upstream image's static gosu binary embeds an outdated Go standard
# library. su-exec supports the same `user command ...` invocation used by the
# PostgreSQL entrypoint. Keep removal and replacement in separate layers so
# scanners correctly honor the whiteout and do not report the removed binary.
RUN rm -f /usr/local/bin/gosu
RUN cp /sbin/su-exec /usr/local/bin/gosu \
    && test "$(/usr/local/bin/gosu postgres id -u)" = "$(id -u postgres)"

# The named data volume inherits the image directory's postgres ownership. This
# lets the default stack drop every capability and start without a root phase.
USER postgres
