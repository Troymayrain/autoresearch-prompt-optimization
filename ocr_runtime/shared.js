const axios = require('axios');
const crypto = require('crypto');
const { downloadImageToBase64, uploadToS3, listLocalImageFiles } = require('./utils');
const { sanitizeRecognitionPayload } = require('./log-sanitizer');

function stableSecretFingerprint(secret) {
  if (typeof secret !== 'string') return null;
  const trimmed = secret.trim();
  if (!trimmed) return null;
  return crypto.createHash('sha256').update(trimmed).digest('hex').slice(0, 12);
}

function normalizeAxiosHeaders(headers) {
  if (!headers || typeof headers !== 'object') return {};
  if (typeof headers.toJSON === 'function') return headers.toJSON();
  return { ...headers };
}

function getHeaderValue(headers, headerName) {
  const normalized = normalizeAxiosHeaders(headers);
  const target = String(headerName).toLowerCase();
  for (const [key, value] of Object.entries(normalized)) {
    if (key.toLowerCase() === target) return value;
  }
  return undefined;
}

function extractBearerToken(authorizationValue) {
  if (authorizationValue == null) return null;
  const raw = String(authorizationValue).trim();
  if (!raw) return null;
  const match = raw.match(/^Bearer\s+(.+)$/i);
  return (match ? match[1] : raw).trim();
}

function formatAIErrorMessage(error) {
  const errorMsg =
    error?.response?.data?.error?.message ||
    error?.error?.message ||
    error?.message ||
    String(error);

  const isRateLimit =
    error?.response?.status === 429 ||
    Number(error?.error?.code) === 429 ||
    Number(error?.response?.data?.error?.code) === 429;

  const msg = typeof errorMsg === 'string' ? errorMsg : String(errorMsg);
  if (!isRateLimit) return msg;
  return msg.startsWith('RATE_LIMIT:') ? msg : `RATE_LIMIT:${msg}`;
}

/**
 * 统一的 API 错误日志记录（避免泄露请求头/密钥）
 * @param {any} error - axios 错误对象或其他异常
 * @param {'detect'|'recognize'} operation - 操作类型
 * @param {object} context - 上下文信息
 * @param {object} [context.aiConfig] - AI 配置
 * @param {string} [context.userId] - 用户标识
 * @param {number|string} [context.imageIndex] - 图片索引
 * @returns {object} 结构化日志数据
 */
function logAPIError(error, operation, context = {}) {
  const { aiConfig, userId, imageIndex } = context;

  const logData = {
    operation,
    timestamp: new Date().toISOString(),
    model: aiConfig?.model,
    provider: aiConfig?.name || 'AI Gateway',
    userId: userId || 'unknown',
    imageIndex: imageIndex !== undefined ? imageIndex : 'N/A',
  };

  const configKeyFp = stableSecretFingerprint(aiConfig?.api_key);
  if (configKeyFp) logData.apiKeyFp = configKeyFp;

  // OpenRouter层异常
  if (error && typeof error === 'object' && error.response) {
    logData.errorType = 'http';
    logData.httpStatus = error.response.status;
    logData.statusText = error.response.statusText;
    logData.errorResponse = error.response.data;
    logData.responseHeaders = error.response.headers;

    const authHeader = getHeaderValue(error.config?.headers, 'authorization');
    const authToken = extractBearerToken(authHeader);
    const headerFp = stableSecretFingerprint(authToken);
    logData.request = {
      method: error.config?.method,
      url: error.config?.url,
      timeout: error.config?.timeout,
    };
    logData.requestAuth = {
      present: Boolean(authHeader),
      fp: headerFp,
      matchConfig: configKeyFp && headerFp ? configKeyFp === headerFp : null,
    };

    if (error.response.status === 429) {
      const rawHeaders = normalizeAxiosHeaders(error.config?.headers);
      const sanitizedHeaders = { ...rawHeaders };
      if (sanitizedHeaders.authorization || sanitizedHeaders.Authorization) {
        const key = sanitizedHeaders.Authorization ? 'Authorization' : 'authorization';
        sanitizedHeaders[key] = `Bearer [fp:${headerFp || 'unknown'}]`;
      }
      logData.requestHeaders = sanitizedHeaders;
      console.error('[429 限流错误] API 触发限流:', JSON.stringify(logData, null, 2));
    } else if (error.response.status >= 500) {
      console.error('[5xx 服务器错误] API 请求失败:', JSON.stringify(logData, null, 2));
    } else if (error.response.status >= 400) {
      console.error('[4xx 客户端错误] API 请求失败:', JSON.stringify(logData, null, 2));
    } else {
      console.error('[HTTP 错误] API 请求失败:', JSON.stringify(logData, null, 2));
    }
    return logData;
  }

  if (error && typeof error === 'object' && error.request) {
    logData.errorType = 'network';
    logData.message = error.message;
    logData.code = error.code;
    console.error('[网络错误] API 请求失败:', JSON.stringify(logData, null, 2));
    return logData;
  }

  // 上游 provider 异常
  if (error && typeof error === 'object' && error.error) {
    logData.errorType = 'api';
    logData.errorResponse = error;
    console.error('[API_ERROR] API 返回错误:', JSON.stringify(logData, null, 2));
    return logData;
  }

  logData.errorType = 'unknown';
  logData.message = error?.error?.message || error?.message || String(error);
  if (error && typeof error === 'object' && error.stack) logData.stack = error.stack;
  console.error('[未知错误] API 请求失败:', JSON.stringify(logData, null, 2));
  return logData;
}

// 是否使用本地图片（设置为 true 则从本地 images 目录读取图片）
const USE_LOCAL_IMAGES = process.env.USE_LOCAL_IMAGES === 'true';

// 是否启用上传图片到 S3（默认 false）
const ENABLE_S3_UPLOAD = process.env.ENABLE_S3_UPLOAD === 'true';

// 延迟时间配置（毫秒），默认 500ms，设置 DELAY=0 可关闭延迟
const DELAY_MS = 'DELAY' in process.env ? Number(process.env.DELAY) : 500;

// 延迟函数
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

/**
 * 从 JSON 字符串中解析结果
 */
function parseJSONContent(content) {
  try {
    return JSON.parse(content);
  } catch (e) {
    const jsonMatch = content.match(/\[[\s\S]*\]/) || content.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      return JSON.parse(jsonMatch[0]);
    }
    console.warn('无法解析为JSON，返回原始内容:', content);
    return content;
  }
}

function createHttpError(statusCode, message) {
  const error = new Error(message);
  error.statusCode = statusCode;
  return error;
}

function parseRequestPayload(event) {
  if (!event || typeof event !== 'object') {
    throw createHttpError(400, 'Invalid request payload');
  }

  if (!event.body) return event;

  if (typeof event.body === 'string') {
    try {
      return JSON.parse(event.body);
    } catch (error) {
      throw createHttpError(400, 'Invalid JSON body');
    }
  }

  if (typeof event.body === 'object' && event.body !== null) {
    return event.body;
  }

  throw createHttpError(400, 'Invalid request body');
}

function validateBaseRequest(event) {
  if (!event.channel) throw createHttpError(400, 'Missing required parameter: channel');
  if (event.channel === 'TB' && event.origin === undefined) {
    throw createHttpError(400, 'Missing required parameter: origin for TB channel');
  }
}

function validateOcrRequest(event) {
  if (Object.prototype.hasOwnProperty.call(event, 'intact')) {
    throw createHttpError(400, 'Parameter "intact" is no longer supported on OCR URL. Use the Integrity URL instead.');
  }
}

function validateIntegrityRequest(event) {
  if (Object.prototype.hasOwnProperty.call(event, 'type')) {
    throw createHttpError(400, 'Parameter "type" is not supported on Integrity URL.');
  }
  if (Object.prototype.hasOwnProperty.call(event, 'intact')) {
    throw createHttpError(400, 'Parameter "intact" is not supported on Integrity URL.');
  }
}

function validateRequestForMode(event, mode) {
  validateBaseRequest(event);
  if (mode === 'ocr') {
    validateOcrRequest(event);
    return;
  }
  validateIntegrityRequest(event);
}

function getFileUrlArray(event) {
  if (USE_LOCAL_IMAGES) {
    const files = listLocalImageFiles();
    console.log('本地模式：从 images 目录读取图片，共', files.length, '张图片');
    return files;
  }

  if (typeof event.image !== 'string') {
    throw createHttpError(400, 'Invalid image parameter format: expected string');
  }

  return event.image.split('||').filter(Boolean);
}

async function processImageWithDelay(processor, args, index) {
  await delay(index * DELAY_MS);
  return processor(...args);
}

async function collectFileInfoMap(fileUrlArray, { channel, origin, userId }) {
  const fileInfoMap = new Map();
  await Promise.all(
    fileUrlArray.map(async (fileUrl) => {
      try {
        const { base64, md5 } = await downloadImageToBase64({
          channel,
          url: fileUrl,
          origin,
          userId,
          source: USE_LOCAL_IMAGES ? 'local' : 's3'
        });
        if (base64 && md5) {
          fileInfoMap.set(fileUrl, { base64, md5 });
        } else {
          if (!base64 && !md5) console.log(fileUrl, '图片过小');
          if (base64 && !md5) console.log(fileUrl, '图片md5有误');
          fileInfoMap.set(fileUrl, { error: 'Image too small — skipped.' });
        }
      } catch (error) {
        console.error('md5下载图片失败:', fileUrl, userId, error);
        fileInfoMap.set(fileUrl, { error: error.message });
      }
    })
  );
  return fileInfoMap;
}

function buildUniqueFiles(fileInfoMap) {
  const uniqueFiles = new Map();
  fileInfoMap.forEach((info, fileUrl) => {
    if (!info.error) {
      if (!uniqueFiles.has(info.md5)) {
        uniqueFiles.set(info.md5, { fileUrl, base64: info.base64 });
      } else {
        console.log('发现重复文件，跳过处理:', fileUrl);
      }
    }
  });
  return uniqueFiles;
}

async function uploadUniqueFilesIfNeeded(uniqueFiles, shouldUploadToS3) {
  const md5ToS3Url = new Map();
  if (!shouldUploadToS3) return md5ToS3Url;

  await Promise.all(
    Array.from(uniqueFiles.entries()).map(async ([md5, { base64 }]) => {
      try {
        const tempUrl = await uploadToS3(base64);
        md5ToS3Url.set(md5, tempUrl);
      } catch (error) {
        console.error('S3上传失败:', error);
        md5ToS3Url.set(md5, 'error-upload');
      }
    })
  );

  return md5ToS3Url;
}

function buildS3UrlArray(fileUrlArray, fileInfoMap, md5ToS3Url) {
  return fileUrlArray.map(fileUrl => {
    const info = fileInfoMap.get(fileUrl);
    if (!info || info.error) {
      return info?.error?.includes('small') ? 'error-small' : 'error-download';
    }
    return md5ToS3Url.get(info.md5) || 'error-upload';
  });
}

function buildImageStatus({
  mode,
  fileUrlArray,
  fileInfoMap,
  uniqueFiles,
  resultByFileUrl,
  shouldUploadToS3,
  s3Url
}) {
  return fileUrlArray.map((fileUrl, idx) => {
    const info = fileInfoMap.get(fileUrl);
    if (!info || info.error) {
      return info?.error?.includes('small') ? 'error-small' : 'error-download';
    }

    if (shouldUploadToS3) {
      const s3UrlValue = s3Url[idx];
      if (typeof s3UrlValue === 'string' && s3UrlValue.startsWith('error-')) {
        return s3UrlValue;
      }
    }

    const uniqueFile = uniqueFiles.get(info.md5);
    const resultObj = uniqueFile ? resultByFileUrl.get(uniqueFile.fileUrl) : null;
    if (resultObj?.status === 'no-card') return 'no-card';
    if (resultObj?.status === 'error') return 'error';
    if (mode === 'ocr' && resultObj?.status === 'ok' && Array.isArray(resultObj.result) && resultObj.result.length === 0) {
      return 'empty-result';
    }
    return 'ok';
  });
}

// 供 handler-ocr.js 直接调用
async function notifyResult(notifyUrl, requestEvent, returnData, isSuccess) {
  if (!notifyUrl) return;
  console.log(isSuccess ? '发送成功通知' : '发送失败通知', notifyUrl);
  try {
    const notifyPayload = { request: requestEvent, response: returnData };
    const sanitizedPayload = {
      ...notifyPayload,
      response: {
        ...notifyPayload.response,
        data: Array.isArray(notifyPayload.response?.data)
          ? sanitizeRecognitionPayload(notifyPayload.response.data)
          : notifyPayload.response?.data,
      },
    };
    console.log('notifyResult 回调请求详情', notifyUrl, JSON.stringify(sanitizedPayload, null, 2));
    const res = await axios.post(notifyUrl, notifyPayload, { timeout: 20000 });
    console.log('notifyResult 回调请求返回', res.status, JSON.stringify(res.data));
  } catch (notifyError) {
    console.warn(isSuccess ? '成功通知回调失败（不影响主流程）:' : '失败通知回调失败:', notifyError.message);
  }
}

const DETECT_RESPONSE_SCHEMA = {
  type: 'OBJECT',
  properties: {
    hasCode: { type: 'BOOLEAN' }
  },
  required: ['hasCode'],
  additionalProperties: false
};

module.exports = {
  DETECT_RESPONSE_SCHEMA,
  stableSecretFingerprint,
  normalizeAxiosHeaders,
  getHeaderValue,
  extractBearerToken,
  formatAIErrorMessage,
  logAPIError,
  USE_LOCAL_IMAGES,
  ENABLE_S3_UPLOAD,
  DELAY_MS,
  delay,
  parseJSONContent,
  createHttpError,
  parseRequestPayload,
  validateBaseRequest,
  validateOcrRequest,
  validateIntegrityRequest,
  validateRequestForMode,
  getFileUrlArray,
  processImageWithDelay,
  collectFileInfoMap,
  buildUniqueFiles,
  uploadUniqueFilesIfNeeded,
  buildS3UrlArray,
  buildImageStatus,
  notifyResult,
};
