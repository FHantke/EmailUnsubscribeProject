# Enfbot - Docker Host Setup on Ubuntu Server

* Install docker
* *[Optional, if using a VPN]:* Create VPN interfaces
    * i.e. Add */etc/wireguard/vpn1.conf*
* *[Optional]: * Add docker network
    * `docker network create --subnet=XX.XX.XX.XX/N -d bridge -o com.docker.network.bridge.name=d-vpn1 vpn1`
        * Where `XX.XX.XX.XX/N` matches the subnet destination from the wireguard configuration

# Running using docker-compose:
* Example file: *./docker-compose/docker-compose-regular.yml*
    * Uses VPN `passau12`
    * Can connect to ETH's postgres database at `id-hdb-psgr-cp86.ethz.ch` directly (without going over the VPN, which would not work as the port is closed from outside)

## Configuration
1. A container has two network interfaces: the VPN (interface IP `172.72.0.1` which varies between VPNs) and `enfbots-open` (IP `172.21.21.1`)
2. When starting a container its default gateway will be set to the VPN interface (line 8ff)
3. Adds a special route to `id-hdb-psgr-cp86.ethz.ch` (Has IP `192.168.162.162`) via the `enfbots-open` interface


## Finally run the docker containers:
```sh
$ docker compose -f PATH_TO_DOCKER_COMPOSE_YML up regularX 
```
