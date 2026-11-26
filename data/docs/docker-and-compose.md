# Docker Containers and Compose

A container is an isolated process that carries its own filesystem, libraries, and settings. An image is the read-only blueprint a container is started from. Many containers can run from one image, and each is isolated from the others.

## Images and versions

Images are identified by a name and a tag, such as postgres:16. The tag latest moves over time, so using it makes a deployment unrepeatable. Pinning an exact version tag means every deployment pulls the same software, which is a core reproducibility practice.

## Docker Compose

Docker Compose describes several containers in one YAML file, usually named docker-compose.yml. Each entry under services defines one container: its image, environment variables, ports, volumes, and networks. The command docker compose up -d starts everything in the background, and docker compose down stops and removes the containers.

## Persistence with volumes

Files written inside a container are lost when the container is removed. A bind mount connects a host directory to a directory inside the container, written as host-path:container-path. A database that stores its files on a bind-mounted directory keeps its data across container deletion and recreation.

## Restart policies and health checks

A restart policy tells Docker what to do when a container stops. The policy unless-stopped restarts the container after a crash or a system reboot unless an administrator stopped it on purpose. A health check is a command Docker runs periodically to decide whether the service is actually ready. For PostgreSQL, the pg_isready command reports whether the server accepts connections. After the configured number of consecutive failures the container is marked unhealthy.

## Resource limits

Without limits, one container can consume all the memory or CPU on the host. Compose lets an administrator cap each container, for example one CPU and one gigabyte of memory. If a container exceeds its memory limit, the Linux kernel kills it in what is called an out-of-memory or OOM kill.

## Networks and port publishing

Containers attached to the same Docker network reach each other by service name. Publishing a port with 127.0.0.1:5432:5432 exposes it only on the host's loopback address, so it is not reachable from other machines. Leaving off the address, as in 5432:5432, publishes the port on every interface.
