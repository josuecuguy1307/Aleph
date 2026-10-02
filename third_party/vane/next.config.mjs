import path from 'node:path';
import pkg from './package.json' with { type: 'json' };

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  images: {
    // [Aleph · Gate 4 · Fase 6 · §6.a.bis] La lista de hosts remotos quedó VACÍA, y así
    // se queda. Tenía un solo permiso: `s2.googleusercontent.com`, el servicio de
    // favicons de Google que recibía la URL de cada fuente citada — o sea, la lista de
    // lo que el usuario mira. Las cuatro llamadas se re-apuntaron al favicon del propio
    // sitio citado (`EXTIRPACIONES.md` §2). Dejar la lista vacía es lo que hace que la
    // fuga no pueda volver por descuido: sin host permitido, `next/image` no sale.
    remotePatterns: [],
  },
  serverExternalPackages: [
    'pdf-parse',
    'playwright',
    'officeparser',
    'file-type',
  ],
  outputFileTracingIncludes: {
    '/api/**': [
      './node_modules/@napi-rs/canvas/**',
      './node_modules/@napi-rs/canvas-linux-x64-gnu/**',
      './node_modules/@napi-rs/canvas-linux-x64-musl/**',
    ],
  },
  env: {
    NEXT_PUBLIC_VERSION: pkg.version,
  },
  turbopack: {
    root: process.cwd(),
  },
};

export default nextConfig;
