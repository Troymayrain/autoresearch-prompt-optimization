function maskCardValue(value) {
  if (typeof value !== 'string') return value;
  if (value.length <= 4) return '*'.repeat(value.length || 4);
  return `${value.slice(0, 2)}${'*'.repeat(value.length - 4)}${value.slice(-2)}`;
}

function cloneValue(value) {
  if (Array.isArray(value)) {
    return value.map(cloneValue);
  }

  if (!value || typeof value !== 'object') {
    return value;
  }

  const cloned = {};
  for (const [key, child] of Object.entries(value)) {
    cloned[key] = cloneValue(child);
  }
  return cloned;
}

function sanitizeRecognitionPayload(payload) {
  if (Array.isArray(payload)) {
    return payload.map((item) => {
      if (typeof item === 'string') return maskCardValue(item);
      return sanitizeRecognitionPayload(item);
    });
  }

  if (!payload || typeof payload !== 'object') {
    return payload;
  }

  const sanitized = {};
  for (const [key, value] of Object.entries(payload)) {
    if (key === 'number' && typeof value === 'string') {
      sanitized[key] = maskCardValue(value);
      continue;
    }

    if (key === 'cards') {
      sanitized[key] = sanitizeRecognitionPayload(value);
      continue;
    }

    sanitized[key] = cloneValue(value);
  }

  return sanitized;
}

function getProviderContentTarget(logData, providerMode) {
  if (providerMode === 'openrouter') {
    const message = logData?.choices?.[0]?.message;
    if (!message || !Object.prototype.hasOwnProperty.call(message, 'content')) return null;
    return {
      get: () => message.content,
      set: (value) => {
        message.content = value;
      }
    };
  }

  if (providerMode === 'vertex-key' || providerMode === 'vertex-account') {
    const part = logData?.candidates?.[0]?.content?.parts?.[0];
    if (!part || !Object.prototype.hasOwnProperty.call(part, 'text')) return null;
    return {
      get: () => part.text,
      set: (value) => {
        part.text = value;
      }
    };
  }

  return null;
}

function parseRecognitionContent(value) {
  if (typeof value === 'string') {
    return JSON.parse(value);
  }

  if (value && typeof value === 'object') {
    return cloneValue(value);
  }

  return null;
}

function buildSanitizedAIResponseLog(responseData, providerMode) {
  const logData = cloneValue(responseData);
  const target = getProviderContentTarget(logData, providerMode);

  if (!target) return logData;

  try {
    const parsed = parseRecognitionContent(target.get());
    if (parsed == null) return logData;
    target.set(sanitizeRecognitionPayload(parsed));
  } catch (_) {
    // Non-JSON content keeps the original value so business diagnostics remain usable.
  }

  return logData;
}

module.exports = {
  buildSanitizedAIResponseLog,
  maskCardValue,
  sanitizeRecognitionPayload
};
