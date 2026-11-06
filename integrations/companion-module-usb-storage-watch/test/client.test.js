import test from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import https from 'node:https'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { Client } from '../src/client.js'
const token='usw7_1001_r_'+'s'.repeat(43)
test('accepts current rotated/transition and legacy dashboard tokens, rejects scoped integration tokens',()=>{
 for(const prefix of ['usw7_1001_r_','usw7_1001_t_','usw_']) new Client({url:'http://127.0.0.1:8765'},prefix+'s'.repeat(43)).close()
 for(const prefix of ['uswc_','usw7_0_r_','usw7_1001_x_']) assert.throws(()=>new Client({url:'http://127.0.0.1:8765'},prefix+'s'.repeat(43)),/management token/)
})
async function serve(server, fn) { await new Promise(r=>server.listen(0,'127.0.0.1',r));try{await fn(server.address().port)}finally{server.closeAllConnections();await new Promise(r=>server.close(r))} }
function handler(seen) { return (req,res)=>{let body='';req.on('data',v=>body+=v);req.on('end',()=>{
 seen.push({path:req.url,headers:req.headers,body:body?JSON.parse(body):null});res.setHeader('Content-Type','application/json')
 if(req.url==='/api/login') {assert.equal(JSON.parse(body).management_token,token);res.setHeader('Set-Cookie','usw_session=synthetic; HttpOnly; SameSite=Strict');res.end(JSON.stringify({csrf:'csrf-value'}))}
 else {assert.equal(req.headers.cookie,'usw_session=synthetic');assert.equal(req.headers['x-csrf-token'],'csrf-value');assert.equal(req.headers['x-usw-request'],'1');res.end('{"ok":true,"message":"Read"}')}
 })} }
test('real HTTP session login, cookies, exact origin and CSRF reused without query tokens',async()=>{
 const seen=[];await serve(http.createServer(handler(seen)),async port=>{const c=new Client({url:`http://127.0.0.1:${port}`},token);await Promise.all([c.request('fleet-status'),c.request('docker-overview')]);assert.equal(seen.filter(v=>v.path==='/api/login').length,1);assert.ok(seen.every(v=>v.headers.origin===`http://127.0.0.1:${port}`&&!v.path.includes(token)));c.close()})
})
test('TLS rejects untrusted certificate, accepts verified CA/address and never disables verification',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'usw-companion-tls-'))
 try {
  execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',path.join(dir,'key'),'--out',path.join(dir,'cert'),'-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],{stdio:'ignore'})
  const ca=fs.readFileSync(path.join(dir,'cert'),'utf8'),seen=[]
  await serve(https.createServer({key:fs.readFileSync(path.join(dir,'key')),cert:ca},handler(seen)),async port=>{
   const bad=new Client({url:`https://127.0.0.1:${port}`},token);await assert.rejects(bad.request('fleet-status'),/HTTPS verification/);bad.close();assert.equal(seen.length,0)
   const good=new Client({url:`https://127.0.0.1:${port}`,ca},token);await good.request('fleet-status');good.close();assert.equal(seen.length,2)
  })
 } finally {fs.rmSync(dir,{recursive:true,force:true})}
})
test('401 never retries a write; token is redacted; later read may authenticate anew',async()=>{
 let calls=0;await serve(http.createServer((req,res)=>{req.resume();req.on('end',()=>{calls++;res.setHeader('Content-Type','application/json');if(req.url==='/api/login'){res.setHeader('Set-Cookie','usw_session=synthetic');res.end('{"csrf":"csrf"}')}else{res.statusCode=401;res.end(JSON.stringify({error:token}))}})}),async port=>{const c=new Client({url:`http://127.0.0.1:${port}`},token);await assert.rejects(c.request('docker-container-action',{confirm:true}),/redacted/);assert.equal(calls,2);assert.equal(c.cookie,'');c.close()})
})
test('redirect is not followed and bounded timeout does not replay',async()=>{
 let calls=0;await serve(http.createServer((req,res)=>{calls++;req.resume();res.statusCode=302;res.setHeader('Location','https://example.test/');res.end()}),async port=>{const c=new Client({url:`http://127.0.0.1:${port}`},token);await assert.rejects(c.request('fleet-status'),/redirected/);assert.equal(calls,1);c.close()})
 await serve(http.createServer(req=>{calls++;req.resume()}),async port=>{const c=new Client({url:`http://127.0.0.1:${port}`},token);await assert.rejects(c.raw('login',{management_token:token},30),/timed out/);assert.equal(calls,2);c.close()})
})
