# Redis configuration for smol-brain

This directory holds Redis configuration files and optional persistence setup.

## Usage

The `docker-compose.yml` in the project root uses Redis with the following settings:

* **Image**: `redis:7-alpine`
* **Persistence**: Append-only file (AOF) enabled
* **Memory limit**: 512MB with LRU eviction
* **Volume**: `redis-data` mounted at `/data`
* **Port**: 6379 (exposed for debugging, gateways connect internally)

## Custom configuration

To customise Redis settings:

1. Create a `redis.conf` file in this directory
2. Mount it in the compose service:

```yaml
services:
  redis:
    volumes:
      - ./infra/redis/redis.conf:/usr/local/etc/redis/redis.conf:ro
    command: redis-server /usr/local/etc/redis/redis.conf
```

## Example configuration

See [redis.conf.example](./redis.conf.example) for a production-ready configuration with:
- Memory limits and eviction policies
- Security settings
- Performance tuning for cache/rate limiting workloads
- Monitoring via the `INFO` command
