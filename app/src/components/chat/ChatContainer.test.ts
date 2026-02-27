// Test the formatAgentError logic used in ChatContainer
// Function copied from ChatContainer.tsx for unit testing

function formatAgentError(raw: string): string {
  if (raw.includes('does not exist') || raw.includes('NotFoundError'))
    return 'Model not available. Try selecting a different model.';
  if (raw.includes('429') || raw.includes('rate limit'))
    return 'Rate limited. Please wait a moment and try again.';
  if (raw.includes('timeout') || raw.includes('timed out'))
    return 'Request timed out. Please try again.';
  if (raw.includes('401') || raw.includes('authentication') || raw.includes('api_key'))
    return 'Authentication error. Check your API key configuration.';
  if (raw.includes('Resource limit')) return 'Resource limit exceeded for this session.';
  if (raw.includes('budget') || raw.includes('Budget'))
    return 'Usage limit reached. Please try again or purchase more credits.';
  return raw.length > 120 ? raw.slice(0, 120) + '...' : raw;
}

describe('formatAgentError', () => {
  it('returns budget error message for LiteLLM budget exceeded', () => {
    expect(formatAgentError('Budget has been exceeded for key sk-xxx')).toBe(
      'Usage limit reached. Please try again or purchase more credits.'
    );
  });

  it('matches lowercase budget errors', () => {
    expect(formatAgentError('budget_exceeded: limit reached')).toBe(
      'Usage limit reached. Please try again or purchase more credits.'
    );
  });

  it('returns model not found for missing models', () => {
    expect(formatAgentError('Model gpt-5 does not exist')).toBe(
      'Model not available. Try selecting a different model.'
    );
  });

  it('returns model not found for NotFoundError', () => {
    expect(formatAgentError('NotFoundError: model not available')).toBe(
      'Model not available. Try selecting a different model.'
    );
  });

  it('returns rate limit message for 429 errors', () => {
    expect(formatAgentError('Error 429: rate limit exceeded')).toBe(
      'Rate limited. Please wait a moment and try again.'
    );
  });

  it('returns rate limit message for rate limit text', () => {
    expect(formatAgentError('rate limit reached, please slow down')).toBe(
      'Rate limited. Please wait a moment and try again.'
    );
  });

  it('returns timeout message for timed out', () => {
    expect(formatAgentError('Request timed out after 30s')).toBe(
      'Request timed out. Please try again.'
    );
  });

  it('returns timeout message for timeout keyword', () => {
    expect(formatAgentError('Connection timeout')).toBe('Request timed out. Please try again.');
  });

  it('returns auth error for 401', () => {
    expect(formatAgentError('401 authentication failed')).toBe(
      'Authentication error. Check your API key configuration.'
    );
  });

  it('returns auth error for authentication keyword', () => {
    expect(formatAgentError('authentication required')).toBe(
      'Authentication error. Check your API key configuration.'
    );
  });

  it('returns auth error for api_key keyword', () => {
    expect(formatAgentError('invalid api_key provided')).toBe(
      'Authentication error. Check your API key configuration.'
    );
  });

  it('returns resource limit message', () => {
    expect(formatAgentError('Resource limit exceeded')).toBe(
      'Resource limit exceeded for this session.'
    );
  });

  it('truncates long unknown errors', () => {
    const longError = 'x'.repeat(200);
    const result = formatAgentError(longError);
    expect(result.length).toBeLessThanOrEqual(123); // 120 + '...'
    expect(result.endsWith('...')).toBe(true);
  });

  it('truncates to exactly 120 chars plus ellipsis', () => {
    const longError = 'a'.repeat(200);
    const result = formatAgentError(longError);
    expect(result).toBe('a'.repeat(120) + '...');
  });

  it('passes through short unknown errors unchanged', () => {
    expect(formatAgentError('Something went wrong')).toBe('Something went wrong');
  });

  it('passes through exactly 120 char errors unchanged', () => {
    const exact120 = 'z'.repeat(120);
    expect(formatAgentError(exact120)).toBe(exact120);
  });

  it('truncates 121 char errors', () => {
    const error121 = 'z'.repeat(121);
    const result = formatAgentError(error121);
    expect(result).toBe('z'.repeat(120) + '...');
  });

  it('handles empty string', () => {
    expect(formatAgentError('')).toBe('');
  });

  it('prioritizes earlier matches over budget check', () => {
    // If a message contains both '401' and 'budget', the 401 check comes first
    expect(formatAgentError('401 budget exceeded')).toBe(
      'Authentication error. Check your API key configuration.'
    );
  });
});
