import { normalizeCost, normalizeStatus } from '../api';

describe('normalizeStatus', () => {
  it('returns safe defaults for an empty response', () => {
    const status = normalizeStatus({});

    expect(status.provider).toBeNull();
    expect(status.model).toBe('');
    expect(status.uptime_seconds).toBe(0);
    expect(status.gateway_port).toBe(0);
    expect(status.paired).toBe(false);
    expect(status.channels).toEqual({});
    expect(status.health.components).toEqual({});
  });

  it('returns safe defaults for non-object payloads', () => {
    for (const junk of [null, undefined, 'oops', 42, [1, 2, 3]]) {
      const status = normalizeStatus(junk);
      expect(status.channels).toEqual({});
      expect(status.health.components).toEqual({});
    }
  });

  it('preserves a well-formed payload', () => {
    const status = normalizeStatus({
      provider: 'openai',
      model: 'test-model',
      temperature: 0.7,
      uptime_seconds: 3600,
      gateway_port: 8080,
      locale: 'en',
      memory_backend: 'sqlite',
      paired: true,
      channels: { telegram: true, discord: false },
      health: {
        pid: 123,
        updated_at: '2026-01-01T00:00:00Z',
        uptime_seconds: 3600,
        components: {
          gateway: {
            status: 'ok',
            updated_at: '2026-01-01T00:00:00Z',
            last_ok: '2026-01-01T00:00:00Z',
            last_error: null,
            restart_count: 2,
          },
        },
      },
    });

    expect(status.provider).toBe('openai');
    expect(status.channels).toEqual({ telegram: true, discord: false });
    expect(status.health.components.gateway?.status).toBe('ok');
    expect(status.health.components.gateway?.restart_count).toBe(2);
  });

  it('coerces malformed nested fields instead of crashing', () => {
    const status = normalizeStatus({
      uptime_seconds: 'not-a-number',
      gateway_port: NaN,
      channels: { telegram: 'yes', discord: true },
      health: {
        components: {
          gateway: { status: 42, restart_count: 'many' },
          broken: null,
        },
      },
    });

    expect(status.uptime_seconds).toBe(0);
    expect(status.gateway_port).toBe(0);
    // Non-boolean channel values degrade to inactive
    expect(status.channels).toEqual({ telegram: false, discord: true });
    expect(status.health.components.gateway?.status).toBe('unknown');
    expect(status.health.components.gateway?.restart_count).toBe(0);
    expect(status.health.components.broken?.status).toBe('unknown');
  });
});

describe('normalizeCost', () => {
  it('returns zeroed totals for an empty response', () => {
    const cost = normalizeCost({});

    expect(cost.session_cost_usd).toBe(0);
    expect(cost.daily_cost_usd).toBe(0);
    expect(cost.monthly_cost_usd).toBe(0);
    expect(cost.total_tokens).toBe(0);
    expect(cost.request_count).toBe(0);
    expect(cost.by_model).toEqual({});
  });

  it('preserves a well-formed payload', () => {
    const cost = normalizeCost({
      session_cost_usd: 0.5,
      daily_cost_usd: 1.25,
      monthly_cost_usd: 10,
      total_tokens: 5000,
      request_count: 42,
      by_model: {
        'test-model': { model: 'test-model', cost_usd: 10, total_tokens: 5000, request_count: 42 },
      },
    });

    expect(cost.session_cost_usd).toBe(0.5);
    expect(cost.by_model['test-model']?.cost_usd).toBe(10);
  });

  it('coerces malformed model stats and fills a missing model name from the key', () => {
    const cost = normalizeCost({
      total_tokens: null,
      by_model: { 'test-model': { cost_usd: 'free' } },
    });

    expect(cost.total_tokens).toBe(0);
    expect(cost.by_model['test-model']?.model).toBe('test-model');
    expect(cost.by_model['test-model']?.cost_usd).toBe(0);
    expect(cost.by_model['test-model']?.total_tokens).toBe(0);
  });
});
