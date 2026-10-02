/* ALEPH · configuración pública del cliente. CONTRACT-AUTH-v2.

   POR QUÉ LA ANON KEY ESTÁ ACÁ Y NO EN UN SECRETO: es PÚBLICA POR DISEÑO. Viaja a
   cada browser que abre la app — cualquiera la lee con Ctrl+U. Lo que protege los datos
   NO es su secreto: es RLS del lado de Supabase (y en nuestro caso, además, que las
   tablas propias ni se exponen por PostREST: `expose-new-tables` está OFF).

   Esconderla no daría un gramo de seguridad y sí crearía una trampa: un clon fresco del
   repo sin config, con el login roto y sin mensaje que lo explique.

   ⚠️ LO QUE NUNCA VA ACÁ: la service_role key, el connection string de la base, las keys
   del procesador de pagos. Todo eso es server-side y vive en el panel de Render. Si
   alguna vez alguien está por pegar algo en este archivo y duda, la respuesta es no. */
window.ALEPH_SUPABASE = {
  url: "https://vinsmikauqlpmqdcihax.supabase.co",
  anonKey: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZpbnNtaWthdXFscG1xZGNpaGF4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQ1NjkzODIsImV4cCI6MjEwMDE0NTM4Mn0.fZpgxGSS7z060oE35GRJ7DtXw5aQ4WqT8uY0YJEITcc",

  // A dónde vuelve el usuario tras el OAuth. DEBE estar en la allowlist de Supabase
  // (Authentication → URL Configuration → Redirect URLs) o el login falla con
  // "requested path is invalid" — un error que no menciona la allowlist por ningún lado.
  redirectTo: (window.location.origin + "/Home.dc.html"),

  // Los métodos VISIBLES. magic-link y email+password quedan afuera hasta que exista
  // dominio propio: sin él el correo no llega de forma fiable, y un botón que falla es
  // peor que un botón que no está (ver CONTRACT-AUTH-v2 §3).
  metodos: ["google", "github"]
};
