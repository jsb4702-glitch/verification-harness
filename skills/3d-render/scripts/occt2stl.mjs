import occtimportjs from '~/stp-assets/occt-import-js.js';
import fs from 'fs';
const occt = await occtimportjs({ locateFile:(f)=>'~/stp-assets/'+f });
const buf = fs.readFileSync(process.argv[2]);
const params={ linearUnit:'millimeter', linearDeflectionType:'absolute_value', linearDeflection:0.15, angularDeflection:0.3 };
const res = occt.ReadStepFile(new Uint8Array(buf), params);
if(!res.success){ console.error('FAIL'); process.exit(1); }
let tris=0, out=[];
for(const m of res.meshes){
  const P=m.attributes.position.array, I=m.index.array;
  for(let i=0;i<I.length;i+=3){
    const a=[P[3*I[i]],P[3*I[i]+1],P[3*I[i]+2]], b=[P[3*I[i+1]],P[3*I[i+1]+1],P[3*I[i+1]+2]], c=[P[3*I[i+2]],P[3*I[i+2]+1],P[3*I[i+2]+2]];
    out.push([a,b,c]); tris++;
  }
}
// binary STL
const bufo=Buffer.alloc(84+tris*50);
bufo.writeUInt32LE(tris,80);
let o=84;
for(const [a,b,c] of out){
  const ux=b[0]-a[0],uy=b[1]-a[1],uz=b[2]-a[2], vx=c[0]-a[0],vy=c[1]-a[1],vz=c[2]-a[2];
  let nx=uy*vz-uz*vy, ny=uz*vx-ux*vz, nz=ux*vy-uy*vx;
  const L=Math.hypot(nx,ny,nz)||1; nx/=L;ny/=L;nz/=L;
  bufo.writeFloatLE(nx,o);bufo.writeFloatLE(ny,o+4);bufo.writeFloatLE(nz,o+8);
  let p=o+12;
  for(const v of [a,b,c]){ bufo.writeFloatLE(v[0],p);bufo.writeFloatLE(v[1],p+4);bufo.writeFloatLE(v[2],p+8); p+=12; }
  o+=50;
}
fs.writeFileSync(process.argv[3],bufo);
console.log('tris',tris,'meshes',res.meshes.length);
