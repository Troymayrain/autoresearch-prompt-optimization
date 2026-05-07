const { buildSanitizedAIResponseLog } = require('./log-sanitizer');
const { callAI, getRandomAIConfig } = require('./ai-provider');
const PROMPTS_CONFIG = require('./prompts');
const {
  USE_LOCAL_IMAGES,
  ENABLE_S3_UPLOAD,
  DETECT_RESPONSE_SCHEMA,
  parseJSONContent,
  createHttpError,
  parseRequestPayload,
  validateRequestForMode,
  getFileUrlArray,
  processImageWithDelay,
  collectFileInfoMap,
  buildUniqueFiles,
  uploadUniqueFilesIfNeeded,
  buildS3UrlArray,
  buildImageStatus,
  formatAIErrorMessage,
  logAPIError,
  notifyResult,
} = require('./shared');

const PROMPT_PREFIX = PROMPTS_CONFIG.PROMPT_PREFIX || '';
const PROMPT_SUFFIX = PROMPTS_CONFIG.PROMPT_SUFFIX || '';
const PROMPT_DETECT = PROMPTS_CONFIG.PROMPT_DETECT || '';
const TYPE_PROMPTS = {
  simple: PROMPTS_CONFIG.PROMPT_SIMPLE || '',
  complex: PROMPTS_CONFIG.PROMPT_COMPLEX || '',
  complete: PROMPTS_CONFIG.PROMPT_COMPLET || ''  // 保持 key 名不变
};

const OCR_SIMPLE_RESPONSE_SCHEMA = {
  type: 'ARRAY',
  items: { type: 'STRING' }
};

const OCR_COMPLEX_RESPONSE_SCHEMA = {
  type: 'ARRAY',
  items: {
    type: 'OBJECT',
    properties: {
      type: { type: 'STRING', enum: ['Physics', 'E-codes'] },
      number: { type: 'STRING' }
    },
    required: ['type', 'number'],
    additionalProperties: false
  }
};

const OCR_COMPLETE_RESPONSE_SCHEMA = {
  type: 'ARRAY',
  items: {
    type: 'OBJECT',
    properties: {
      type: { type: 'STRING', enum: ['Physics', 'E-codes'] },
      cardType: { type: 'STRING' },
      country: { type: 'STRING' },
      currency: { type: 'STRING' },
      denomination: { type: 'STRING' },
      number: { type: 'STRING' }
    },
    required: ['type', 'number'],
    additionalProperties: false
  }
};

const OCR_RESPONSE_SCHEMAS = {
  simple: OCR_SIMPLE_RESPONSE_SCHEMA,
  complex: OCR_COMPLEX_RESPONSE_SCHEMA,
  complete: OCR_COMPLETE_RESPONSE_SCHEMA,
};

/**
 * 获取 OCR 识别提示词
 * @param {string} type - 'simple' | 'complex' | 'complete'
 * @returns {string} OCR 系统提示词
 */
function getOcrPrompt(type = 'simple') {
  const typePrompt = TYPE_PROMPTS[type] || TYPE_PROMPTS.simple;
  return PROMPT_PREFIX + '\n' + typePrompt + '\n' + PROMPT_SUFFIX;
}

function buildOcrErrorResult(type, message) {
  return type === 'simple'
    ? ["error:" + message]
    : [{ error: message }];
}

function buildOcrFallbackResult(type) {
  return type === 'simple'
    ? [""]
    : [{ type: "", number: "" }];
}

function recordModel(models, model) {
  if (Array.isArray(models) && typeof model === 'string' && model) models.push(model);
}

// 第一步：检测图片是否包含卡码
async function detectCardCode(aiConfig, base64Image, providers, userId, imageIndex, models) {
  const { content, model } = await callAI(
    aiConfig,
    PROMPT_DETECT,
    base64Image,
    undefined,
    { responseSchema: DETECT_RESPONSE_SCHEMA }
  );
  recordModel(models, model);
  const result = parseJSONContent(content);
  return result.hasCode === true;
}

async function processOCRSingleImage(aiConfig, base64Image, type, providers, userId, imageIndex, fileUrl, models) {
  let hasCode;
  try {
    hasCode = await detectCardCode(aiConfig, base64Image, providers, userId, imageIndex, models);
  } catch (error) {
    logAPIError(error, 'detect', { aiConfig, userId, imageIndex });
    return {
      status: 'error',
      result: buildOcrErrorResult(type, formatAIErrorMessage(error))
    };
  }

  if (!hasCode) {
    console.log('检测结果：不进行识别（无卡码）', fileUrl);
    return { status: 'no-card', result: [] };
  }

  try {
    const systemText = getOcrPrompt(type);
    const ocrSchema = OCR_RESPONSE_SCHEMAS[type] || OCR_SIMPLE_RESPONSE_SCHEMA;
    const { content, rawResponse, provider, providerMode, model } = await callAI(
      aiConfig,
      systemText,
      base64Image,
      undefined,
      { responseSchema: ocrSchema }
    );
    providers.push(provider);
    recordModel(models, model);

    const logData = buildSanitizedAIResponseLog(rawResponse.data, providerMode);
    console.log('AI返回\n', JSON.stringify(logData, null, 2));

    const result = parseJSONContent(content);
    const resultArray = Array.isArray(result) ? result : [result];
    return { status: 'ok', result: resultArray };
  } catch (error) {
    logAPIError(error, 'recognize', { aiConfig, userId, imageIndex });
    return {
      status: 'error',
      result: buildOcrErrorResult(type, formatAIErrorMessage(error))
    };
  }
}

function buildOCRData({ type, fileUrlArray, fileInfoMap, uniqueFiles, resultByFileUrl }) {
  const finalResults = fileUrlArray.map(fileUrl => {
    const fileInfo = fileInfoMap.get(fileUrl);
    if (!fileInfo) return buildOcrFallbackResult(type);
    if (fileInfo.error) return buildOcrErrorResult(type, fileInfo.error);

    const uniqueFile = uniqueFiles.get(fileInfo.md5);
    const resultObj = uniqueFile ? resultByFileUrl.get(uniqueFile.fileUrl) : null;
    return resultObj ? resultObj.result : buildOcrFallbackResult(type);
  });

  const mergedResults = finalResults.flat();
  const filterComplexResults = (items) => items.filter((item, index, self) =>
    item.number &&
    item.number.length > 4 &&
    item.number.length < 40 &&
    index === self.findIndex(t => t.number?.toUpperCase() === item.number?.toUpperCase())
  );

  if (type === 'complex' || type === 'complete') {
    return filterComplexResults(mergedResults);
  }

  return mergedResults
    .map(item => typeof item === 'string' ? item.toUpperCase() : (item?.number || item))
    .filter((value, index, self) => {
      const str = typeof value === 'string' ? value : '';
      return str !== '' && !str.startsWith('ERROR:') && str.length > 4 && str.length < 40 && self.indexOf(value) === index;
    });
}

async function processOcrRequest(rawEvent) {
  let s3Url = [];
  let imageStatus = [];
  let providers = [];
  let event = rawEvent;
  let notifyUrl;

  try {
    event = parseRequestPayload(rawEvent);
    notifyUrl = event.notifyUrl;

    validateRequestForMode(event, 'ocr');

    const channel = event.channel;
    const origin = event.origin;
    const userId = event.userId;
    const type = event.type || 'simple';

    console.log('userId', userId);

    const fileUrlArray = getFileUrlArray(event);
    if (fileUrlArray.length === 0) {
      throw createHttpError(400, 'Empty image list provided');
    }

    const shouldUploadToS3 = !USE_LOCAL_IMAGES && ENABLE_S3_UPLOAD;
    const selectedAIConfig = getRandomAIConfig();
    const models = [];
    const totalStartTime = Date.now();
    console.log('开始处理图片 (ocr)');

    const fileInfoMap = await collectFileInfoMap(fileUrlArray, { channel, origin, userId });
    const uniqueFiles = buildUniqueFiles(fileInfoMap);
    const md5ToS3Url = await uploadUniqueFilesIfNeeded(uniqueFiles, shouldUploadToS3);

    const results = await Promise.all(
      Array.from(uniqueFiles.values()).map(async ({ fileUrl, base64 }, index) => {
        try {
          const resultObj = await processImageWithDelay(
            processOCRSingleImage,
            [selectedAIConfig, base64, type, providers, userId, index, fileUrl, models],
            index
          );

          return { fileUrl, status: resultObj.status, result: resultObj.result };
        } catch (error) {
          return {
            fileUrl,
            status: 'error',
            result: buildOcrErrorResult(type, error.message)
          };
        }
      })
    );

    const resultByFileUrl = new Map(results.map(r => [r.fileUrl, r]));

    if (shouldUploadToS3) {
      s3Url = buildS3UrlArray(fileUrlArray, fileInfoMap, md5ToS3Url);
    }

    imageStatus = buildImageStatus({
      mode: 'ocr',
      fileUrlArray,
      fileInfoMap,
      uniqueFiles,
      resultByFileUrl,
      shouldUploadToS3,
      s3Url
    });

    const outputData = buildOCRData({ type, fileUrlArray, fileInfoMap, uniqueFiles, resultByFileUrl });

    console.log('所有图片处理完成');
    const totalEndTime = Date.now();
    const totalDuration = (totalEndTime - totalStartTime) / 1000;

    const returnData = {
      status: 200,
      message: 'success',
      data: outputData,
      duration: totalDuration,
      imageStatus,
      ai: {
        name: selectedAIConfig.name,
        model: models[0] || selectedAIConfig.model,
        providers
      }
    };

    if (shouldUploadToS3) returnData.s3Url = s3Url;
    await notifyResult(notifyUrl, event, returnData, true);

    return {
      statusCode: 200,
      body: returnData,
    };
  } catch (error) {
    console.error('Error:', error);
    const statusCode = Number.isInteger(error?.statusCode) ? error.statusCode : 500;
    const returnData = {
      status: statusCode,
      message: 'failed',
      error: error.message || String(error)
    };

    await notifyResult(notifyUrl, event, returnData, false);

    return {
      statusCode,
      body: returnData,
    };
  }
}

module.exports = {
  processOcrRequest,
  processOCRSingleImage,
  detectCardCode,
  getOcrPrompt,
  buildOcrErrorResult,
  buildOcrFallbackResult,
  buildOCRData,
};
