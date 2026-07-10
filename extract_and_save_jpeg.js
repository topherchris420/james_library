#!/usr/bin/env node
/**
 * Extract JPEG from bundled HTML and save as binary file
 * Run: node extract_and_save_jpeg.js
 */

const fs = require('fs');
const https = require('https');
const path = require('path');

async function downloadFile(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve(data));
    }).on('error', reject);
  });
}

async function main() {
  try {
    console.log('📥 Downloading rain_lab_trifold.html...');
    const html = await downloadFile(
      'https://raw.githubusercontent.com/topherchris420/james_library/main/assets/marketing/rain_lab_trifold.html'
    );

    console.log('🔍 Parsing manifest...');
    const manifestMatch = html.match(/<script type="__bundler\/manifest">\s*(\{[\s\S]*?\})\s*<\/script>/);
    
    if (!manifestMatch) {
      throw new Error('Could not find manifest in HTML');
    }

    const manifest = JSON.parse(manifestMatch[1]);
    
    // Find JPEG entry
    let base64Data = null;
    for (const [uuid, entry] of Object.entries(manifest)) {
      if (entry.mime === 'image/jpeg') {
        base64Data = entry.data;
        console.log(`✓ Found JPEG data (${base64Data.length} characters)`);
        break;
      }
    }

    if (!base64Data) {
      throw new Error('No JPEG found in manifest');
    }

    // Convert base64 to binary
    console.log('🔄 Converting base64 to binary...');
    const binaryBuffer = Buffer.from(base64Data, 'base64');

    // Save to file
    const outputPath = 'assets/marketing/rain_lab_trifold.jpg';
    fs.writeFileSync(outputPath, binaryBuffer);
    
    console.log(`✅ Saved JPEG to: ${outputPath}`);
    console.log(`   File size: ${(binaryBuffer.length / 1024 / 1024).toFixed(2)} MB`);

  } catch (error) {
    console.error('❌ Error:', error.message);
    process.exit(1);
  }
}

main();
