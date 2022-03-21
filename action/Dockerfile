
FROM ghcr.io/vchernin/flatpak-external-data-checker:latest # fixme before merge

RUN apt-get update && \
    apt-get install -y parallel && \
    apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

ADD entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]