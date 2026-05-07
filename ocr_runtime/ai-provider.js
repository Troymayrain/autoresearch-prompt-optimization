const axios = require('axios');

const AI_GATEWAY_TIMEOUT_MS = Number(process.env.AI_GATEWAY_TIMEOUT_MS || 80000);

function getRequiredEnv(name) {
  const value = process.env[name];
  if (typeof value !== 'string' || value.trim() === '') {
    throw new Error(`${name} is required`);
  }
  return value.trim();
}

function getRandomAIConfig() {
  return { name: 'AI Gateway', model: null };
}

function buildGatewayMessages(systemText, base64Image, userText) {
  const userContent = [
    { type: 'image_url', image_url: { url: base64Image } }
  ];
  if (userText) userContent.push({ type: 'text', text: userText });

  return [
    { role: 'system', content: systemText || '' },
    { role: 'user', content: userContent }
  ];
}

function buildGatewayError(status, data) {
  const message = data?.error?.message || data?.message || 'AI Gateway returned error';
  const error = new Error(message);
  error.response = {
    status,
    data,
  };
  return error;
}

function normalizeGatewayResult(responseData) {
  const payload = responseData && typeof responseData === 'object' ? responseData : {};
  if (payload.error || (Number(payload.status) >= 400)) {
    throw buildGatewayError(Number(payload.status) || 502, payload);
  }

  const data = payload.data && typeof payload.data === 'object' ? payload.data : payload;
  return {
    content: data.content,
    rawResponse: { data: data.rawResponse },
    provider: data.provider,
    providerMode: data.providerMode,
    model: data.model,
    fallbackUsed: data.fallbackUsed === true,
    attempts: Array.isArray(data.attempts) ? data.attempts : undefined,
  };
}

async function callAI(aiConfig, systemText, base64Image, userText, options) {
  const gatewayUrl = getRequiredEnv('AI_GATEWAY_URL');
  const gatewayKey = getRequiredEnv('AI_GATEWAY_KEY');
  const messages = buildGatewayMessages(systemText, base64Image, userText);

  const headers = {
    'content-type': 'application/json; charset=utf-8',
    'x-api-key': gatewayKey,
  };
  const body = { messages, options: options || {} };

  try {
    const response = await axios.post(
      gatewayUrl,
      body,
      {
        headers,
        timeout: AI_GATEWAY_TIMEOUT_MS,
      }
    );
    return normalizeGatewayResult(response.data);
  } catch (error) {
    if (error && error.response) throw error;
    throw error;
  }
}

module.exports = {
  callAI,
  getRandomAIConfig,
  buildGatewayMessages,
  AI_GATEWAY_TIMEOUT_MS,
  __test__: {
    buildGatewayError,
    normalizeGatewayResult,
  },
};
