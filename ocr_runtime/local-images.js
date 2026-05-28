const fs = require('fs');
const path = require('path');

const LOCAL_IMAGE_EXTS = new Set(['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff']);

function toPosixPath(value) {
  return String(value).split(path.sep).join('/');
}

function getLocalImagesDir() {
  return (process.env.LOCAL_IMAGES_DIR || '').trim()
    ? path.resolve(process.env.LOCAL_IMAGES_DIR)
    : path.join(__dirname, 'images');
}

// 本地样本枚举需要稳定顺序，否则同一批图片的响应数组不方便比对。
function listImageFilesInDirectory(rootDir) {
  const result = [];

  function walk(currentDir, relativeDir) {
    const entries = fs.readdirSync(currentDir, { withFileTypes: true })
      .filter((entry) => entry.name && !entry.name.startsWith('.'))
      .sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'));

    for (const entry of entries) {
      const relativePath = relativeDir ? path.join(relativeDir, entry.name) : entry.name;
      const fullPath = path.join(currentDir, entry.name);
      if (entry.isDirectory()) {
        walk(fullPath, relativePath);
        continue;
      }
      if (entry.isFile() && LOCAL_IMAGE_EXTS.has(path.extname(entry.name).toLowerCase())) {
        result.push(toPosixPath(relativePath));
      }
    }
  }

  walk(rootDir, '');
  return result;
}

function listLocalImageFiles(rootDir = getLocalImagesDir()) {
  try {
    return listImageFilesInDirectory(path.resolve(rootDir));
  } catch (error) {
    const message = error && typeof error === 'object' ? (error.message || String(error)) : String(error);
    throw new Error(`读取本地 images 目录失败: ${path.resolve(rootDir)} (${message})`);
  }
}

module.exports = {
  LOCAL_IMAGE_EXTS,
  getLocalImagesDir,
  listImageFilesInDirectory,
  listLocalImageFiles,
};
