
export async function prepareFaceImage(file: File): Promise<File> {
  const bitmap = await createImageBitmap(file);

  try {
    const maxDimension = 2048;
    const scale = Math.min(
      1,
      maxDimension / Math.max(bitmap.width, bitmap.height)
    );

    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));

    const context = canvas.getContext('2d');
    if (!context) {
      throw new Error('Image processing failed');
    }

    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (result) => result
          ? resolve(result)
          : reject(new Error('Image compression failed')),
        'image/jpeg',
        0.88
      );
    });

    const baseName = file.name.replace(/\.[^.]+$/, '') || 'face';

    return new File([blob], `${baseName}.jpg`, {
      type: 'image/jpeg'
    });
  } finally {
    bitmap.close();
  }
}
