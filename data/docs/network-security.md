# Network Security on a Cloud Deployment

Security is built in layers, so that a mistake in one layer does not expose the whole system. A cloud web application commonly uses a network firewall, host-level controls, container network isolation, and careful secret handling.

## Firewall rules

A cloud firewall allows or denies traffic by port, protocol, and source address. A public web service typically allows ports 80 and 443 from anywhere and denies everything else. Databases and inference servers should never have a public rule. They should accept connections only from other machines or containers inside the private network.

## Restricting SSH

Port 22 is a common target for automated attacks. Two good defenses are limiting the allowed source addresses and using Identity-Aware Proxy tunneling, which lets only authenticated cloud users reach the SSH port without exposing it to the internet. Password logins should be disabled in favor of keys.

## Verifying exposure

A firewall is only trustworthy if it is tested from the outside. The tool nmap scans a host and reports which ports respond, and curl or nc can probe a single port. A correct result from outside the network shows ports 80 and 443 open while the database port 5432 and the inference port 11434 are filtered or closed.

## Container isolation

Docker networks keep containers apart unless they share a network. Binding a published port to 127.0.0.1 limits it to the host itself. These measures complement the cloud firewall rather than replace it.

## Secrets

A secret is any password, token, or key. Secrets must not be committed to Git. A secret manager stores them centrally and hands them to a machine at runtime, based on that machine's service account permissions. If a secret is ever committed by accident, deleting the file is not enough, because Git history keeps it. The secret must be rotated, meaning replaced with a new value.

## Least privilege

Each person and each machine should have only the permissions its job needs. A virtual machine that only reads one secret should have a service account allowed to read that secret and nothing broader.
