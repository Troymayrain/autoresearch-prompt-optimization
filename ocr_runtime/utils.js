const axios = require("axios");
const CryptoJS = require('crypto-js');
const path = require("path");
const fs = require("fs");
const crypto = require('crypto');
const imageSize = require('image-size');
const sizeOf = typeof imageSize === 'function' ? imageSize : imageSize.default;
const { getLocalImagesDir, listLocalImageFiles } = require('./local-images');

const S3_READ_REGION = (process.env.S3_READ_REGION || '').trim() || 'eu-central-1';
const S3_WRITE_REGION = (process.env.S3_WRITE_REGION || '').trim() || 'ap-east-1';
const S3_TEMP_BUCKET = (process.env.S3_TEMP_BUCKET || '').trim() || 'ai-code-ocr-temp';

let awsS3 = null;
let presigner = null;
let s3Client = null;
let s3Upload = null;

function getAwsS3() {
  if (!awsS3) awsS3 = require('@aws-sdk/client-s3');
  return awsS3;
}

function getPresigner() {
  if (!presigner) presigner = require('@aws-sdk/s3-request-presigner');
  return presigner;
}

function getS3ReadClient() {
  if (!s3Client) {
    const { S3Client } = getAwsS3();
    s3Client = new S3Client({ region: S3_READ_REGION });
  }
  return s3Client;
}

function getS3WriteClient() {
  if (!s3Upload) {
    const { S3Client } = getAwsS3();
    s3Upload = new S3Client({ region: S3_WRITE_REGION });
  }
  return s3Upload;
}

// 本地 images 目录路径
const LOCAL_IMAGES_DIR = getLocalImagesDir();

// 本地调试允许传子目录相对路径，但绝不允许 ../ 逃逸出 images 根目录读取任意文件。
function resolveLocalImagePath(requestedPath) {
  const value = String(requestedPath || '');
  const candidate = path.resolve(LOCAL_IMAGES_DIR, value);
  const root = path.resolve(LOCAL_IMAGES_DIR);
  if ((candidate === root || candidate.startsWith(`${root}${path.sep}`)) && fs.existsSync(candidate)) {
    return candidate;
  }

  const fileName = path.basename(value);
  const allFiles = listLocalImageFiles(LOCAL_IMAGES_DIR);
  const match = allFiles.find(f => path.basename(String(f)) === fileName);
  if (!match) {
    throw new Error(`本地图片不存在: ${fileName}`);
  }
  return path.join(LOCAL_IMAGES_DIR, String(match));
}

// 从本地 images 目录获取图片内容
const getImageFromLocal = async (url) => {
  try {
    const localPath = resolveLocalImagePath(url);
    const fileName = path.basename(String(url || ''));

    console.log('从本地读取图片:', localPath);
    const imageData = fs.readFileSync(localPath);
    console.log('成功从本地读取图片:', fileName, '大小:', imageData.length, 'bytes');
    return imageData;
  } catch (error) {
    console.error('从本地读取图片失败:', error.message || error);
    throw new Error(`从本地读取图片失败: ${error.message || error}`);
  }
};

const arrayBufferToBase64 = (buffer) => {
  let binary = '';
  let bytes = new Uint8Array(buffer);
  let len = bytes.byteLength;
  for (var i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return Buffer.from(binary, 'binary').toString('base64');
};

const calculateMD5 = (buffer) => {
  return crypto.createHash('md5').update(buffer).digest('hex');
};

/** 增加T矩阵解密 26.03.04 */
const decryptImageTM = async (url, imageData, uid) => {
  if (url.indexOf("tccard/") >= 0) {
    let urlLast8 = url
      .split(".png")[0]
      .slice(-8);
    let uidLast = uid.slice(-16);
    // 在lambda 的环境变量中增加 T矩阵 DEC_SALT_TM 解密key  26.03.04
    let salt = `${process.env.DEC_SALT_TM}${uidLast}${urlLast8}`;
    let keyHex = CryptoJS.enc.Hex.parse(salt);
    let bytes = new Int8Array(imageData);
    let newByteArrData = arrayBufferToBase64(bytes).trim().replace(/[\r\n]/g, "");
    let decryptByteArrData = CryptoJS.AES.decrypt(newByteArrData, keyHex, {
      mode: CryptoJS.mode.ECB,
      padding: CryptoJS.pad.Pkcs7,
    });
    const decryptDataString = CryptoJS.enc.Base64.stringify(decryptByteArrData);
    const bufferObj = Buffer.from(decryptDataString, 'base64');
    return Buffer.from(decryptDataString, 'base64').toString('utf8');
  } else {
    return Buffer.from(imageData, 'binary').toString('base64')
  }
}

const decryptImageCG = async (url, imageData, uid) => {
  if (url.indexOf("reserc2/card/") >= 0) {
    if (!uid) {
      throw new Error('Missing required parameter: userId for reserc2 encrypted images');
    }
    let urlLast8 = url
      .split(".png")[0]
      .substring(url.length - 12);
    // 验证解密盐值环境变量
    if (!process.env.DEC_SALT_CG) {
      console.warn('警告: DEC_SALT_CG 环境变量未设置，解密可能失败');
    }
    let salt = `${process.env.DEC_SALT_CG || ''}${urlLast8}${uid}`;
    let MD5salt = CryptoJS.MD5(salt);
    let bytes = new Int8Array(imageData);
    var key = CryptoJS.enc.Utf8.parse(MD5salt);
    let iv = CryptoJS.enc.Utf8.parse(MD5salt);

    let base64ByteArr = arrayBufferToBase64(bytes);

    let decryptByteArrData = CryptoJS.AES.decrypt(base64ByteArr, key, {
      iv: iv,
      mode: CryptoJS.mode.ECB,
      padding: CryptoJS.pad.Pkcs7,
    });
    const decryptDataString = decryptByteArrData.toString(CryptoJS.enc.Base64);
    return Buffer.from(decryptDataString, 'base64').toString('utf8');
  } else if (url.indexOf("reserc/card/") >= 0) {
    let urlLast8 = url
      .split(".png")[0]
      .substring(url.length - 12);

    // 验证解密盐值环境变量
    if (!process.env.DEC_SALT_CG) {
      console.warn('警告: DEC_SALT_CG 环境变量未设置，解密可能失败');
    }
    let salt = `${process.env.DEC_SALT_CG || ''}${urlLast8}`;
    let MD5salt = CryptoJS.MD5(salt);
    let bytes = new Int8Array(imageData);
    var key = CryptoJS.enc.Utf8.parse(MD5salt);
    let iv = CryptoJS.enc.Utf8.parse(MD5salt);

    let base64ByteArr = arrayBufferToBase64(bytes);

    let decryptByteArrData = CryptoJS.AES.decrypt(base64ByteArr, key, {
      iv: iv,
      mode: CryptoJS.mode.ECB,
      padding: CryptoJS.pad.Pkcs7,
    });
    const decryptDataString = decryptByteArrData.toString(CryptoJS.enc.Base64);
    return Buffer.from(decryptDataString, 'base64').toString('utf8');
  } else {
    return Buffer.from(imageData, 'binary').toString('base64')
  }
}

const decryptImageTB = async (url, imageData, origin, uid = null) => {
  // 验证解密盐值环境变量
  if (!process.env.DEC_SALT_TB) {
    console.warn('警告: DEC_SALT_TB 环境变量未设置，解密可能失败');
  }
  const saltBase = process.env.DEC_SALT_TB || '';

  if (url.startsWith("amazon_aws/card_img_tbay/")) {
    let urlLast8 = url
      .split(".png")[0]
      .slice(parseInt(origin) !== 10 ? -8 : -24);
    let salt = `${saltBase}${urlLast8}`;
    let keyHex = CryptoJS.enc.Hex.parse(salt.replace('U', '1'));
    let bytes = new Int8Array(imageData);
    let newByteArrData = arrayBufferToBase64(bytes);
    let decryptByteArrData = CryptoJS.AES.decrypt(newByteArrData, keyHex, {
      mode: CryptoJS.mode.ECB,
      padding: CryptoJS.pad.Pkcs7,
    });
    const decryptDataString = CryptoJS.enc.Base64.stringify(decryptByteArrData);
    return Buffer.from(decryptDataString, 'base64').toString('utf8');
  } else if (url.startsWith('amazon_aws/card_img_tbay_v2/')) {
    if (!uid) {
      throw new Error('Missing required parameter: userId for card_img_tbay_v2 encrypted images');
    }
    let salt = `${saltBase}${uid}`;
    let keyHex = CryptoJS.enc.Hex.parse(salt.replace('U', '1'));
    let bytes = new Int8Array(imageData);
    let newByteArrData = arrayBufferToBase64(bytes);
    let decryptByteArrData = CryptoJS.AES.decrypt(newByteArrData, keyHex, {
      mode: CryptoJS.mode.ECB,
      padding: CryptoJS.pad.Pkcs7,
    });
    const decryptDataString = CryptoJS.enc.Base64.stringify(decryptByteArrData);
    const base64Result = Buffer.from(decryptDataString, 'base64').toString('utf8');

    // 验证解密结果是否为有效图片，无效则用 card_img_tbay 逻辑重试
    try {
      sizeOf(Buffer.from(base64Result, 'base64'));
      return base64Result;
    } catch (e) {
      console.warn('card_img_tbay_v2 解密结果无效，回退 card_img_tbay 逻辑重试:', e.message);
      let urlLast8 = url.split('.png')[0].slice(parseInt(origin) !== 10 ? -8 : -24);
      let fallbackSalt = `${saltBase}${urlLast8}`;
      let fallbackKey = CryptoJS.enc.Hex.parse(fallbackSalt.replace('U', '1'));
      let fallbackDecrypt = CryptoJS.AES.decrypt(newByteArrData, fallbackKey, {
        mode: CryptoJS.mode.ECB,
        padding: CryptoJS.pad.Pkcs7,
      });
      const fallbackDataString = CryptoJS.enc.Base64.stringify(fallbackDecrypt);
      return Buffer.from(fallbackDataString, 'base64').toString('utf8');
    }
  } else if (url.startsWith('652daaac6db1271aa95ff0a8bc3502cb/')) {
    if (!uid) {
      throw new Error('Missing required parameter: userId for 652daaac encrypted images');
    }
    let salt = `${saltBase}${uid}`;
    let keyHex = CryptoJS.enc.Hex.parse(salt.replace('U', '1'));
    let bytes = new Int8Array(imageData);
    let newByteArrData = arrayBufferToBase64(bytes);
    let decryptByteArrData = CryptoJS.AES.decrypt(newByteArrData, keyHex, {
      mode: CryptoJS.mode.ECB,
      padding: CryptoJS.pad.Pkcs7,
    });
    const decryptDataString = CryptoJS.enc.Base64.stringify(decryptByteArrData);
    return Buffer.from(decryptDataString, 'base64').toString('utf8');
  } else {
    return Buffer.from(imageData, 'binary').toString('base64')
  }
}

// 从 S3 获取图片内容
const getImageFromS3 = async (bucket, key) => {
  try {
    const { GetObjectCommand } = getAwsS3();
    const command = new GetObjectCommand({
      Bucket: bucket,
      Key: key
    });

    const response = await getS3ReadClient().send(command);

    // 读取流数据并转换为 buffer
    return await streamToBuffer(response.Body);
  } catch (error) {
    throw new Error(`从 S3 获取图片失败: ${error.message || error}`);
  }
};

// 将流转换为 buffer
const streamToBuffer = async (stream) => {
  const chunks = [];

  for await (const chunk of stream) {
    chunks.push(chunk instanceof Buffer ? chunk : Buffer.from(chunk));
  }

  return Buffer.concat(chunks);
};

/**
 * 下载图片并转换为 Base64
 * @param {Object} options - 配置选项
 * @param {string} options.channel - 渠道类型 ('TB' | 'CG')
 * @param {string} options.url - 图片URL或路径
 * @param {string} [options.origin] - 来源标识
 * @param {string} [options.userId] - 用户ID
 * @param {'s3'|'local'|'http'} [options.source='s3'] - 图片来源 ('s3' | 'local' | 'http')
 */
const downloadImageToBase64 = async (options) => {
  const {
    channel,
    url,
    origin = null,
    userId = null,
    source = 's3'
  } = options;

  try {
    let imageData;

    if (source === 'local') {
      // 从本地 images 目录读取图片
      console.log('使用本地模式读取图片');
      imageData = await getImageFromLocal(url);
    } else if (source === 's3') {
      // 从 S3 获取图片
      // const bucket = channel === 'TB' ? (url.startsWith('amazon_aws/') ? 'gx-card-pro' : 'tbay-card-prod') : (channel=== 'CG'? process.env.S3_BUCKET_CG : process.env.S3_BUCKET_TM); //channel === 'CG' ? process.env.S3_BUCKET_CG : process.env.S3_BUCKET_TB;
      const bucket = channel === 'TB' ? (url.startsWith('amazon_aws/') ? process.env.S3_BUCKET_TB_GX : process.env.S3_BUCKET_TB_TBAY) : (channel === 'CG' ? process.env.S3_BUCKET_CG : process.env.S3_BUCKET_TM); //channel === 'CG' ? process.env.S3_BUCKET_CG : process.env.S3_BUCKET_TB;
      const key = url.startsWith('652daaac6db1271aa95ff0a8bc3502cb/') ? 'giftcard/' + url : url; // 假设 url 就是 S3 对象的 key，如有必要可以进一步处理
      imageData = await getImageFromS3(bucket, key);
    } else {
      // HTTP 下载方式
      const imgUrl = (channel === 'CG' ? process.env.IMAGE_URL_CG : process.env.IMAGE_URL_TB) + url;
      console.log('imgUrl', imgUrl);

      const response = await axios.get(imgUrl, {
        responseType: 'arraybuffer',
        timeout: 10000
      });

      imageData = response.data;
    }


    let base64Image;
    if (channel === 'CG') {
      base64Image = await decryptImageCG(url, imageData, userId);
    } else if (channel === 'TB') {
      base64Image = await decryptImageTB(url, imageData, origin, userId);
    } else if (channel === 'TM') { // 增加T矩阵的判断  26.03.04
      base64Image = await decryptImageTM(url, imageData, userId);
    } else {
      base64Image = Buffer.from(imageData, 'binary').toString('base64');
    }

    let buffer = Buffer.from(base64Image, 'base64');
    const dimensions = sizeOf(buffer);

    if (base64Image && dimensions.height > 150 && dimensions.width > 150) {
      const finalBase64 = buffer.toString('base64');

      // 计算图片的 MD5（使用二进制 Buffer，与 uploadToS3 保持一致）
      const md5 = calculateMD5(buffer);

      return {
        base64: `data:image/png;base64,${finalBase64}`,
        md5
      };
    } else {
      return { base64: null, md5: null };
    }
  } catch (error) {
    throw new Error(`处理图片失败: ${error.message || error}`);
  }
}

const uploadToS3 = async (base64Image) => {
  const { GetObjectCommand, PutObjectCommand } = getAwsS3();
  const { getSignedUrl } = getPresigner();
  const buffer = Buffer.from(base64Image.replace('data:image/png;base64,', ''), 'base64');
  const md5 = crypto.createHash('md5').update(buffer).digest('hex');
  // 文件名可用时间戳等方式生成唯一名
  const fileName = `${md5}.png`;

  await getS3WriteClient().send(new PutObjectCommand({
    Bucket: S3_TEMP_BUCKET,
    Key: fileName,
    Body: buffer,
    ContentType: 'image/png',
  }));

  // 生成预签名 URL（有效期 1 小时）
  const command = new GetObjectCommand({
    Bucket: S3_TEMP_BUCKET,
    Key: fileName,
  });

  const signedUrl = await getSignedUrl(getS3WriteClient(), command, { expiresIn: 3600 }); // 1 小时有效

  return signedUrl;

}

const isBase64 = (str) => {
  if (typeof str !== 'string') return false;

  // 去除换行符和空格
  str = str.trim().replace(/\r?\n|\r/g, '');

  // Base64 字符合法性校验
  const notBase64 = /[^A-Z0-9+\/=]/i;
  if (str.length % 4 !== 0 || notBase64.test(str)) {
    return false;
  }

  try {
    const decoded = Buffer.from(str, 'base64').toString('utf-8');
    // 可选：重新编码验证是否一致
    // return Buffer.from(decoded, 'utf-8').toString('base64') === str;
    return true;
  } catch (err) {
    return false;
  }
}

const decodeBase64ToJson = (base64Str) => {
  try {
    const jsonStr = Buffer.from(base64Str, 'base64').toString('utf-8');
    return JSON.parse(jsonStr);
  } catch (err) {
    console.error('解码失败:', err);
    return null;
  }
}
module.exports = {
  downloadImageToBase64, uploadToS3, isBase64, decodeBase64ToJson
};
