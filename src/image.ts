import sharp from "sharp";

export async function processImage(filePath: string): Promise<string> {
  const image = sharp(filePath);
  const metadata = await image.metadata();

  let pipeline = image;
  if (metadata.width && metadata.width > 1280) {
    pipeline = pipeline.resize({ width: 1280 });
  }

  const buffer = await pipeline.jpeg({ quality: 85 }).toBuffer();
  return `data:image/jpeg;base64,${buffer.toString("base64")}`;
}
