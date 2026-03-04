#!/usr/bin/env node
/**
 * Generate favicon files from the SVG source.
 * Run: node scripts/generate-favicons.js
 *
 * Produces files in app/public/:
 *   favicon.ico          (48x48)
 *   favicon-32x32.png    (32x32)
 *   favicon-16x16.png    (16x16)
 *   apple-touch-icon.png (180x180)
 *   android-chrome-192x192.png (192x192)
 *   android-chrome-512x512.png (512x512)
 */

const sharp = require("sharp");
const { sharpsToIco } = require("sharp-ico");
const path = require("path");
const fs = require("fs");

const SVG_PATH = path.resolve(__dirname, "../app/public/favicon.svg");
const OUT_DIR = path.resolve(__dirname, "../app/public");

const SIZES = [
  { name: "favicon-16x16.png", size: 16 },
  { name: "favicon-32x32.png", size: 32 },
  { name: "apple-touch-icon.png", size: 180 },
  { name: "android-chrome-192x192.png", size: 192 },
  { name: "android-chrome-512x512.png", size: 512 },
];

async function main() {
  const svgBuffer = fs.readFileSync(SVG_PATH);

  // Generate PNGs
  for (const { name, size } of SIZES) {
    await sharp(svgBuffer, { density: 300 })
      .resize(size, size, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
      .png()
      .toFile(path.join(OUT_DIR, name));
    console.log(`  Created ${name} (${size}x${size})`);
  }

  // Generate ICO (48x48 — Google requires multiples of 48px)
  const ico48 = sharp(svgBuffer, { density: 300 })
    .resize(48, 48, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png();

  await sharpsToIco([ico48], path.join(OUT_DIR, "favicon.ico"), { sizes: [48] });
  console.log("  Created favicon.ico (48x48)");

  console.log("\nDone! All favicon files written to app/public/");
}

main().catch((err) => {
  console.error("Error generating favicons:", err);
  process.exit(1);
});
