import { extractFeatures, suggestWindows, toMono } from "../../app/static/suggest.js";
const rate=22050, N=rate*150; const x=new Float32Array(N);
const midi=m=>440*2**((m-69)/12);
function note(t0,t1,m,amp){for(let i=Math.floor(t0*rate);i<Math.min(N,Math.floor(t1*rate));i++){const t=i/rate;x[i]+=amp*Math.sin(2*Math.PI*midi(m)*t)+0.3*amp*Math.sin(4*Math.PI*midi(m)*t);}}
// sections (seconds): intro 0-8, verse1 8-38, chorus 38-68, verse2 68-98 (different notes), chorus 98-128, outro 128-150
const chorus=[[60,64,67],[65,69,72],[67,71,74],[60,64,67]];
function chorusAt(s){for(let b=0;b<30;b++){const ch=chorus[b%4];ch.forEach(m=>note(s+b,s+b+1,m,0.30));}}
function verseAt(s,base){for(let b=0;b<30;b++){note(s+b,s+b+1,base+[0,3,5,7,3,2][b%6],0.08);}}
verseAt(8,52); chorusAt(38); verseAt(68,55); chorusAt(98);
for(let b=0;b<8;b++) note(b,b+1,48+b%3,0.05); for(let b=0;b<22;b++) note(128+b,129+b,50+b%2,0.04);
const mono=toMono([x],rate);
const found=suggestWindows(extractFeatures(mono.samples,mono.rate),30,3);
const tooShort=suggestWindows(extractFeatures(mono.samples.slice(0,mono.rate*12),mono.rate),30,3);
console.log(JSON.stringify({found,tooShort}));
