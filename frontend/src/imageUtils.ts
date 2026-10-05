import { getDict } from "./i18n";

export const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];
export const MAX_UPLOAD_MB = 5; // must match the backend MAX_IMAGE_MB default
const MAX_PICK_MB = 25; // refuse absurdly large originals before even trying to decode them
const MAX_SIDE = 1600;
const SKIP_RESIZE_BELOW_BYTES = 1.5 * 1024 * 1024;

export class ImageProblem extends Error {}

/**
 * Validate a chosen photo and, if it is large, shrink it in the browser (max 1600 px, JPEG ~0.85)
 * so ordinary phone photos fit the upload limit and uploads stay fast. Any failure while resizing
 * falls back to the original file. The server still validates everything independently.
 * Messages come from the active-language dictionary.
 */
export async function prepareImage(file: File): Promise<File> {
  const msg = getDict().analyze;
  if (!ALLOWED_TYPES.includes(file.type)) throw new ImageProblem(msg.photoUnsupported);
  if (file.size > MAX_PICK_MB * 1024 * 1024) throw new ImageProblem(msg.photoTooLarge);

  let result = file;
  try {
    const bitmap = await createImageBitmap(file);
    const longest = Math.max(bitmap.width, bitmap.height);
    if (longest > MAX_SIDE || file.size > SKIP_RESIZE_BELOW_BYTES) {
      const scale = Math.min(1, MAX_SIDE / longest);
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, "image/jpeg", 0.85));
        if (blob && blob.size < file.size) {
          result = new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
        }
      }
    }
    bitmap.close?.();
  } catch {
    result = file; // cannot decode/resize here: send the original and let the server decide
  }

  if (result.size > MAX_UPLOAD_MB * 1024 * 1024) throw new ImageProblem(msg.photoTooLarge);
  return result;
}
