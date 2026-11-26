#!/bin/sh
set -eu

: "${ADA_AI_PRIVATE_IP:?Set ADA_AI_PRIVATE_IP to the private address of ada-ai}"
: "${ADA_AI_RATE_LIMIT:=30}"

envsubst '${ADA_AI_PRIVATE_IP} ${ADA_AI_RATE_LIMIT}' \
  < /usr/local/etc/haproxy/haproxy.cfg.template \
  > /tmp/haproxy.cfg
exec haproxy -W -db -f /tmp/haproxy.cfg
