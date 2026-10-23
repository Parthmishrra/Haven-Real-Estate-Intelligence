import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {extractiveAnswer,retrieve} from '../dist/retrieval.mjs';
const {documents}=JSON.parse(fs.readFileSync(new URL('../dist/assets/sample-data.json',import.meta.url)));
test('selected property isolation',()=>{const r=extractiveAnswer('What is the rent?',documents,'cedar');assert.match(r.text,/32,000/);assert.doesNotMatch(r.text,/48,000/);assert.ok(r.sources.every(s=>s.property_id==='cedar'));});
test('pets cite community rules',()=>{const r=retrieve('Are pets allowed?',documents,'canopy');assert.match(r[0].text,/two domestic pets/);assert.equal(r[0].doc_id,'canopy-hoa');});
test('unknown answer abstains',()=>{const r=extractiveAnswer('intergalactic flux capacitor',documents,'canopy');assert.equal(r.sources.length,0);assert.match(r.text,/couldn’t find/);});
test('deletion removes source',()=>{const r=retrieve('Are pets allowed?',documents.filter(d=>d.id!=='canopy-hoa'),'canopy');assert.ok(r.every(s=>s.doc_id!=='canopy-hoa'));});
