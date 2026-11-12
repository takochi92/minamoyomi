/** Geometry of the displayed video, in the same pixels as a Chrome screenshot. */
export async function readVideoLayout(cdp) {
  return cdp.evaluate(`(() => {
    const video = document.querySelector('video');
    if (!video?.videoWidth || !video.videoHeight || devicePixelRatio !== 1) return null;
    const style = getComputedStyle(video);
    if (style.objectPosition !== '50% 50%' || style.transform !== 'none') return null;
    if (['Top', 'Right', 'Bottom', 'Left'].some(side =>
      parseFloat(style['border' + side + 'Width']) || parseFloat(style['padding' + side]))) return null;
    const {x, y, width, height} = video.getBoundingClientRect();
    const native = [video.videoWidth, video.videoHeight];
    const viewport = [innerWidth, innerHeight];
    let [w, h] = [width, height];
    if (style.objectFit === 'contain' || style.objectFit === 'scale-down') {
      const scale = Math.min(width / native[0], height / native[1],
        style.objectFit === 'scale-down' ? 1 : Infinity);
      [w, h] = native.map(n => n * scale);
    } else if (style.objectFit !== 'fill') return null;
    if (w <= 0 || h <= 0 || Math.abs(w - h * native[0] / native[1]) > 2) return null;
    const left = x + (width - w) / 2;
    const top = y + (height - h) / 2;
    if (left < -0.01 || top < -0.01 || left + w > innerWidth + 0.01 ||
        top + h > innerHeight + 0.01) return null;
    const box = [Math.max(0, left), Math.max(0, top), Math.min(innerWidth, left + w),
      Math.min(innerHeight, top + h)];
    return {native, viewport, box};
  })()`);
}

export function stableVideoLayout(before, after, screenshot, frame) {
  if (!before || !after || before.viewport[0] !== screenshot.width ||
      before.viewport[1] !== screenshot.height) return null;
  if (before.native[0] !== frame?.width || before.native[1] !== frame?.height) return null;
  if (JSON.stringify(before) !== JSON.stringify(after)) return null;
  return before;
}
