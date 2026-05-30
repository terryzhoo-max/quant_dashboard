const fs = require('fs');
const lines = fs.readFileSync('d:/FIONA/google AI/quant_dashboard/quant_dashboard/strategy.html', 'utf8').split('\n');

let inERP = false;
let depth = 0;

for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (l.includes('id="st-erp-timing"')) {
        inERP = true;
        depth = 0;
        console.log('ERP START at line', i + 1);
    }
    if (inERP) {
        const opens = (l.match(/<div[\s>]/g) || []).length;
        const closes = (l.match(/<\/div>/g) || []).length;
        depth += opens - closes;
        if (depth <= 0 && i > 8117) {
            console.log('ERP CLOSED at line', i + 1, 'depth=', depth);
            inERP = false;
            break;
        }
    }
}

// Now check: what element contains st-erp-timing
let containerDepth = 0;
for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (l.includes('class="content pf-content"')) {
        console.log('\ncontent pf-content at line', i + 1);
    }
    if (l.includes('id="st-erp-timing"')) {
        console.log('st-erp-timing at line', i + 1, '(container depth would be based on DOM)');
        break;
    }
}

// Check if element can be found by getElementById
console.log('\nTotal lines:', lines.length);
const erpLines = lines.filter(l => l.includes('st-erp-timing'));
console.log('Lines mentioning st-erp-timing:', erpLines.length);
erpLines.forEach((l, idx) => console.log(`  ${idx}: ${l.trim().substring(0, 100)}`));
