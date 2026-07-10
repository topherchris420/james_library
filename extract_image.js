const fs = require('fs');
const path = require('path');

// Read the HTML file
const htmlPath = path.join(__dirname, 'assets/marketing/rain_lab_trifold.html');
const html = fs.readFileSync(htmlPath, 'utf-8');

// Extract the manifest JSON
const manifestMatch = html.match(/script type="__bundler\/manifest">({.*?})<\/script/s);
if (!manifestMatch) {
  console.error('Could not find manifest');
  process.exit(1);
}

const manifest = JSON.parse(manifestMatch[1]);

// Find the JPEG entry
let found = false;
for (const [uuid, entry] of Object.entries(manifest)) {
  if (entry.mime === 'image/jpeg') {
    console.log(`Found JPEG: ${uuid}`);
    console.log(`Data length: ${entry.data.length} characters`);
    
    // Convert base64 to Buffer
    const buffer = Buffer.from(entry.data, 'base64');
    
    // Save as file in the same directory
    const outputPath = path.join(__dirname, 'assets/marketing/rain_lab_trifold.jpg');
    fs.writeFileSync(outputPath, buffer);
    console.log(`✓ Image saved to ${outputPath}`);
    console.log(`✓ File size: ${(buffer.length / 1024).toFixed(2)} KB`);
    found = true;
    break;
  }
}

if (!found) {
  console.error('No JPEG found in manifest');
  process.exit(1);
}
